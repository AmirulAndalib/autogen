import asyncio
from abc import ABC, abstractmethod
from typing import Any, List, Sequence

from autogen_core import CancellationToken, DefaultTopicId, MessageContext, event, rpc

from ...base import TerminationCondition
from ...messages import BaseAgentEvent, BaseChatMessage, MessageFactory, SelectSpeakerEvent, StopMessage
from ._events import (
    GroupChatAgentResponse,
    GroupChatError,
    GroupChatMessage,
    GroupChatPause,
    GroupChatRequestPublish,
    GroupChatReset,
    GroupChatResume,
    GroupChatStart,
    GroupChatTeamResponse,
    GroupChatTermination,
    SerializableException,
)
from ._sequential_routed_agent import SequentialRoutedAgent


class BaseGroupChatManager(SequentialRoutedAgent, ABC):
    """Base class for a group chat manager that manages a group chat with multiple participants.

    It is the responsibility of the caller to ensure:
    - All participants must subscribe to the group chat topic and each of their own topics.
    - The group chat manager must subscribe to the group chat topic.
    - The agent types of the participants must be unique.
    - For each participant, the agent type must be the same as the topic type.

    Without the above conditions, the group chat will not function correctly.
    """

    def __init__(
        self,
        name: str,
        group_topic_type: str,
        output_topic_type: str,
        participant_topic_types: List[str],
        participant_names: List[str],
        participant_descriptions: List[str],
        output_message_queue: asyncio.Queue[BaseAgentEvent | BaseChatMessage | GroupChatTermination],
        termination_condition: TerminationCondition | None,
        max_turns: int | None,
        message_factory: MessageFactory,
        emit_team_events: bool = False,
    ):
        super().__init__(
            description="Group chat manager",
            sequential_message_types=[
                GroupChatStart,
                GroupChatAgentResponse,
                GroupChatTeamResponse,
                GroupChatMessage,
                GroupChatReset,
            ],
        )
        if max_turns is not None and max_turns <= 0:
            raise ValueError("The maximum number of turns must be greater than 0.")
        if len(participant_topic_types) != len(participant_descriptions):
            raise ValueError("The number of participant topic types, agent types, and descriptions must be the same.")
        if len(set(participant_topic_types)) != len(participant_topic_types):
            raise ValueError("The participant topic types must be unique.")
        if group_topic_type in participant_topic_types:
            raise ValueError("The group topic type must not be in the participant topic types.")
        self._name = name
        self._group_topic_type = group_topic_type
        self._output_topic_type = output_topic_type
        self._participant_names = participant_names
        self._participant_name_to_topic_type = {
            name: topic_type for name, topic_type in zip(participant_names, participant_topic_types, strict=True)
        }
        self._participant_descriptions = participant_descriptions
        self._message_thread: List[BaseAgentEvent | BaseChatMessage] = []
        self._output_message_queue = output_message_queue
        self._termination_condition = termination_condition
        self._max_turns = max_turns
        self._current_turn = 0
        self._message_factory = message_factory
        self._emit_team_events = emit_team_events
        self._active_speakers: List[str] = []

    @rpc
    async def handle_start(self, message: GroupChatStart, ctx: MessageContext) -> None:
        """Handle the start of a group chat by selecting a speaker to start the conversation."""

        # Check if the conversation has already terminated.
        if self._termination_condition is not None and self._termination_condition.terminated:
            early_stop_message = StopMessage(
                content="The group chat has already terminated.",
                source=self._name,
            )
            # Signal termination to the caller of the team.
            await self._signal_termination(early_stop_message)
            # Stop the group chat.
            return

        # Validate the group state given the start messages
        await self.validate_group_state(message.messages)

        if message.messages is not None:
            # Log all messages at once
            await self.publish_message(
                GroupChatStart(messages=message.messages),
                topic_id=DefaultTopicId(type=self._output_topic_type),
            )

            # Only put messages in output queue if output_task_messages is True
            if message.output_task_messages:
                for msg in message.messages:
                    await self._output_message_queue.put(msg)

            # Relay all messages at once to participants
            await self.publish_message(
                GroupChatStart(messages=message.messages),
                topic_id=DefaultTopicId(type=self._group_topic_type),
                cancellation_token=ctx.cancellation_token,
            )

            # Append all messages to thread
            await self.update_message_thread(message.messages)

            # Check termination condition after processing all messages
            if await self._apply_termination_condition(message.messages):
                # Stop the group chat.
                return

        # Select speakers to start/continue the conversation
        await self._transition_to_next_speakers(ctx.cancellation_token)

    @event
    async def handle_agent_response(
        self, message: GroupChatAgentResponse | GroupChatTeamResponse, ctx: MessageContext
    ) -> None:
        try:
            # Construct the detla from the agent response.
            delta: List[BaseAgentEvent | BaseChatMessage] = []
            if isinstance(message, GroupChatAgentResponse):
                if message.response.inner_messages is not None:
                    for inner_message in message.response.inner_messages:
                        delta.append(inner_message)
                delta.append(message.response.chat_message)
            else:
                delta.extend(message.result.messages)

            # Append the messages to the message thread.
            await self.update_message_thread(delta)

            # Remove the agent from the active speakers list.
            self._active_speakers.remove(message.name)
            if len(self._active_speakers) > 0:
                # If there are still active speakers, return without doing anything.
                return

            # Check if the conversation should be terminated.
            if await self._apply_termination_condition(delta, increment_turn_count=True):
                # Stop the group chat.
                return

            # Select speakers to continue the conversation.
            await self._transition_to_next_speakers(ctx.cancellation_token)
        except Exception as e:
            # Handle the exception and signal termination with an error.
            error = SerializableException.from_exception(e)
            await self._signal_termination_with_error(error)
            # Raise the exception to the runtime.
            raise

    async def _transition_to_next_speakers(self, cancellation_token: CancellationToken) -> None:
        speaker_names_future = asyncio.ensure_future(self.select_speaker(self._message_thread))
        # Link the select speaker future to the cancellation token.
        cancellation_token.link_future(speaker_names_future)
        speaker_names = await speaker_names_future
        if isinstance(speaker_names, str):
            # If only one speaker is selected, convert it to a list.
            speaker_names = [speaker_names]
        for speaker_name in speaker_names:
            if speaker_name not in self._participant_name_to_topic_type:
                raise RuntimeError(f"Speaker {speaker_name} not found in participant names.")
        await self._log_speaker_selection(speaker_names)

        # Send request to publish message to the next speakers
        for speaker_name in speaker_names:
            speaker_topic_type = self._participant_name_to_topic_type[speaker_name]
            await self.publish_message(
                GroupChatRequestPublish(),
                topic_id=DefaultTopicId(type=speaker_topic_type),
                cancellation_token=cancellation_token,
            )
            self._active_speakers.append(speaker_name)

    async def _apply_termination_condition(
        self, delta: Sequence[BaseAgentEvent | BaseChatMessage], increment_turn_count: bool = False
    ) -> bool:
        """Apply the termination condition to the delta and return True if the conversation should be terminated.
        It also resets the termination condition and turn count, and signals termination to the caller of the team."""
        if self._termination_condition is not None:
            stop_message = await self._termination_condition(delta)
            if stop_message is not None:
                # Reset the termination conditions and turn count.
                await self._termination_condition.reset()
                self._current_turn = 0
                # Signal termination to the caller of the team.
                await self._signal_termination(stop_message)
                # Stop the group chat.
                return True
        if increment_turn_count:
            # Increment the turn count.
            self._current_turn += 1
        # Check if the maximum number of turns has been reached.
        if self._max_turns is not None:
            if self._current_turn >= self._max_turns:
                stop_message = StopMessage(
                    content=f"Maximum number of turns {self._max_turns} reached.",
                    source=self._name,
                )
                # Reset the termination conditions and turn count.
                if self._termination_condition is not None:
                    await self._termination_condition.reset()
                self._current_turn = 0
                # Signal termination to the caller of the team.
                await self._signal_termination(stop_message)
                # Stop the group chat.
                return True
        return False

    async def _log_speaker_selection(self, speaker_names: List[str]) -> None:
        """Log the selected speaker to the output message queue."""
        select_msg = SelectSpeakerEvent(content=speaker_names, source=self._name)
        if self._emit_team_events:
            await self.publish_message(
                GroupChatMessage(message=select_msg),
                topic_id=DefaultTopicId(type=self._output_topic_type),
            )
            await self._output_message_queue.put(select_msg)

    async def _signal_termination(self, message: StopMessage) -> None:
        termination_event = GroupChatTermination(message=message)
        # Log the early stop message.
        await self.publish_message(
            termination_event,
            topic_id=DefaultTopicId(type=self._output_topic_type),
        )
        # Put the termination event in the output message queue.
        await self._output_message_queue.put(termination_event)

    async def _signal_termination_with_error(self, error: SerializableException) -> None:
        termination_event = GroupChatTermination(
            message=StopMessage(content="An error occurred in the group chat.", source=self._name), error=error
        )
        # Log the termination event.
        await self.publish_message(
            termination_event,
            topic_id=DefaultTopicId(type=self._output_topic_type),
        )
        # Put the termination event in the output message queue.
        await self._output_message_queue.put(termination_event)

    @event
    async def handle_group_chat_message(self, message: GroupChatMessage, ctx: MessageContext) -> None:
        """Handle a group chat message by appending the content to its output message queue."""
        await self._output_message_queue.put(message.message)

    @event
    async def handle_group_chat_error(self, message: GroupChatError, ctx: MessageContext) -> None:
        """Handle a group chat error by logging the error and signaling termination."""
        await self._signal_termination_with_error(message.error)

    @rpc
    async def handle_reset(self, message: GroupChatReset, ctx: MessageContext) -> None:
        """Reset the group chat manager. Calling :meth:`reset` to reset the group chat manager
        and clear the message thread."""
        await self.reset()

    @rpc
    async def handle_pause(self, message: GroupChatPause, ctx: MessageContext) -> None:
        """Pause the group chat manager. This is a no-op in the base class."""
        pass

    @rpc
    async def handle_resume(self, message: GroupChatResume, ctx: MessageContext) -> None:
        """Resume the group chat manager. This is a no-op in the base class."""
        pass

    @abstractmethod
    async def validate_group_state(self, messages: List[BaseChatMessage] | None) -> None:
        """Validate the state of the group chat given the start messages.
        This is executed when the group chat manager receives a GroupChatStart event.

        Args:
            messages: A list of chat messages to validate, or None if no messages are provided.
        """
        ...

    async def update_message_thread(self, messages: Sequence[BaseAgentEvent | BaseChatMessage]) -> None:
        """Update the message thread with the new messages.
        This is called when the group chat receives a GroupChatStart or GroupChatAgentResponse event,
        before calling the select_speakers method.
        """
        self._message_thread.extend(messages)

    @abstractmethod
    async def select_speaker(self, thread: Sequence[BaseAgentEvent | BaseChatMessage]) -> List[str] | str:
        """Select speakers from the participants and return the topic types of the selected speaker.
        This is called when the group chat manager have received all responses from the participants
        for a turn and is ready to select the next speakers for the next turn.

        Args:
            thread: The message thread of the group chat.

        Returns:
            A list of topic types of the selected speakers.
            If only one speaker is selected, a single string is returned instead of a list.
        """
        ...

    @abstractmethod
    async def reset(self) -> None:
        """Reset the group chat manager."""
        ...

    async def on_unhandled_message(self, message: Any, ctx: MessageContext) -> None:
        raise ValueError(f"Unhandled message in group chat manager: {type(message)}")
