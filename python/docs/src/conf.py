# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

from sphinx.application import Sphinx
from typing import Any, Dict
from pathlib import Path
import sys
import os
import subprocess
# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

import autogen_core

project = "autogen_core"
copyright = "2024, Microsoft"
author = "Microsoft"
version = "0.4"

release_override = os.getenv("SPHINX_RELEASE_OVERRIDE")
if release_override is None or release_override == "":
    release = autogen_core.__version__
else:
    release = release_override

sys.path.append(str(Path(".").resolve()))

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    "sphinx.ext.napoleon",
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.todo",
    "sphinx.ext.viewcode",
    "sphinx.ext.intersphinx",
    "sphinx.ext.graphviz",
    "sphinxext.rediraffe",
    "sphinx_design",
    "sphinx_copybutton",
    "_extension.gallery_directive",
    "myst_nb",
    "sphinxcontrib.autodoc_pydantic",
    "_extension.code_lint",
]
suppress_warnings = ["myst.header"]

napoleon_custom_sections = [("Returns", "params_style")]

templates_path = ["_templates"]

autoclass_content = "class"

# TODO: incldue all notebooks excluding those requiring remote API access.
nb_execution_mode = "off"

# Guides and tutorials must succeed.
nb_execution_raise_on_error = True
nb_execution_timeout = 60

myst_heading_anchors = 5

myst_enable_extensions = [
    "colon_fence",
    "linkify",
    "strikethrough",
]

if (path := os.getenv("PY_DOCS_DIR")) is None:
    path = "dev"


if (switcher_version := os.getenv("PY_SWITCHER_VERSION")) is None:
    switcher_version = "dev"

html_baseurl = f"/autogen/{path}/"

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_title = "AutoGen"

html_theme = "pydata_sphinx_theme"
html_static_path = ["_static"]
html_css_files = ["custom.css"]

add_module_names = False

html_logo = "_static/images/logo/logo.svg"
html_favicon = "_static/images/logo/favicon-512x512.png"

html_theme_options = {
    "header_links_before_dropdown": 6,
    "navbar_align": "left",
    "check_switcher": False,
    # "navbar_start": ["navbar-logo", "version-switcher"],
    # "switcher": {
    #     "json_url": "/_static/switcher.json",
    # },
    "show_prev_next": True,
    "icon_links": [
        {
            "name": "GitHub",
            "url": "https://github.com/microsoft/autogen",
            "icon": "fa-brands fa-github",
        },
        {
            "name": "Discord",
            "url": "https://aka.ms/autogen-discord",
            "icon": "fa-brands fa-discord",
        },
        {
            "name": "Twitter",
            "url": "https://twitter.com/pyautogen",
            "icon": "fa-brands fa-twitter",
        }
    ],

    "footer_start": ["copyright"],
    "footer_center": ["footer-middle-links"],
    "footer_end": ["theme-version", "version-banner-override"],
    "pygments_light_style": "xcode",
    "pygments_dark_style": "monokai",
    "navbar_start": ["navbar-logo", "version-switcher"],
    "switcher": {
        "json_url": "https://raw.githubusercontent.com/microsoft/autogen/refs/heads/main/docs/switcher.json",
        "version_match": switcher_version,
    },
    "show_version_warning_banner": True,
    "external_links": [
      {"name": ".NET", "url": "https://microsoft.github.io/autogen/dotnet/"},
      {"name": "0.2 Docs", "url": "https://microsoft.github.io/autogen/0.2/"},
    ]
}

html_js_files = ["custom-icon.js", "banner-override.js", "custom.js"]
html_sidebars = {
    "packages/index": [],
    "user-guide/core-user-guide/**": ["sidebar-nav-bs-core"],
    "user-guide/agentchat-user-guide/**": ["sidebar-nav-bs-agentchat"],
    "user-guide/extensions-user-guide/**": ["sidebar-nav-bs-extensions"],
    "user-guide/autogenstudio-user-guide/**": ["sidebar-nav-bs-studio"],
}

html_context = {
    'display_github': True,
    "github_user": "microsoft",
    "github_repo": "autogen",
    "github_version": "main",
    "doc_path": "python/docs/src/",
}

autodoc_default_options = {
    "members": True,
    "undoc-members": True,
}

autodoc_pydantic_model_show_config_summary = False
autodoc_pydantic_model_show_json_error_strategy = "coerce"
python_use_unqualified_type_names = True
autodoc_preserve_defaults = True

intersphinx_mapping = {"python": ("https://docs.python.org/3", None)}

code_lint_path_prefix = "reference/python"

nb_mime_priority_overrides = [
  ('code_lint', 'image/jpeg', 100),
  ('code_lint', 'image/png', 100),
  ('code_lint', 'text/plain', 100)
]

rediraffe_redirects = {
    "user-guide/agentchat-user-guide/tutorial/selector-group-chat.ipynb": "user-guide/agentchat-user-guide/selector-group-chat.ipynb",
    "user-guide/agentchat-user-guide/tutorial/swarm.ipynb": "user-guide/agentchat-user-guide/swarm.ipynb",
    "user-guide/core-user-guide/framework/command-line-code-executors.ipynb": "user-guide/core-user-guide/components/command-line-code-executors.ipynb",
    "user-guide/core-user-guide/framework/model-clients.ipynb": "user-guide/core-user-guide/components/model-clients.ipynb",
    "user-guide/core-user-guide/framework/tools.ipynb": "user-guide/core-user-guide/components/tools.ipynb",
    "user-guide/agentchat-user-guide/tutorial/custom-agents.ipynb": "user-guide/agentchat-user-guide/custom-agents.ipynb",
}


def generate_api_reference() -> None:
    """Generate API documentation before building."""
    reference_dir = Path(__file__).parent / "reference"
    
    # Only generate if reference directory doesn't exist
    if reference_dir.exists():
        print("📁 Reference directory already exists, skipping API generation")
        return
    
    script_path = Path(__file__).parent / "generate_api_reference.py"
    if script_path.exists():
        print("🔄 Generating API documentation...")
        try:
            result = subprocess.run(
                [sys.executable, str(script_path)],
                cwd=script_path.parent,
                capture_output=True,
                text=True,
                check=True
            )
            print("✅ API documentation generated successfully")
            # Print the output for visibility
            if result.stdout:
                for line in result.stdout.strip().split('\n'):
                    print(f"   {line}")
        except subprocess.CalledProcessError as e:
            print(f"❌ Failed to generate API documentation: {e}")
            if e.stdout:
                print(f"stdout: {e.stdout}")
            if e.stderr:
                print(f"stderr: {e.stderr}")
            # Don't fail the build, just warn
    else:
        print(f"⚠️  API documentation generator not found at {script_path}")


def setup_to_main(
    app: Sphinx, pagename: str, templatename: str, context, doctree
) -> None:
    """Add a function that jinja can access for returning an "edit this page" link pointing to `main`."""

    def to_main(link: str) -> str:
        """Transform "edit on github" links and make sure they always point to the main branch.

        Args:
            link: the link to the github edit interface

        Returns:
            the link to the tip of the main branch for the same file
        """
        links = link.split("/")
        idx = links.index("edit")
        return "/".join(links[: idx + 1]) + "/main/" + "/".join(links[idx + 2:])

    context["to_main"] = to_main


def setup(app: Sphinx) -> Dict[str, Any]:
    """Add custom configuration to sphinx app.

    Args:
        app: the Sphinx application
    Returns:
        the 2 parallel parameters set to ``True``.
    """
    # Generate API documentation before building
    app.connect("builder-inited", lambda app: generate_api_reference())
    
    app.connect("html-page-context", setup_to_main)

    # Adding here so it is inline and not in a separate file.
    clarity_analytics = """(function(c,l,a,r,i,t,y){
    c[a]=c[a]||function(){(c[a].q=c[a].q||[]).push(arguments)};
    t=l.createElement(r);t.async=1;t.src="https://www.clarity.ms/tag/"+i;
    y=l.getElementsByTagName(r)[0];y.parentNode.insertBefore(t,y);
})(window, document, "clarity", "script", "lnxpe6skj1");"""
    app.add_js_file(None, body=clarity_analytics)

    return {
        "parallel_read_safe": True,
        "parallel_write_safe": True,
    }
