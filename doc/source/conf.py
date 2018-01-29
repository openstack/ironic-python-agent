# -- General configuration ----------------------------------------------------

# Add any Sphinx extension module names here, as strings. They can be
# extensions coming with Sphinx (named 'sphinx.ext.*') or your custom ones.
extensions = ['sphinx.ext.autodoc',
              'sphinx.ext.viewcode',
              'sphinxcontrib.httpdomain',
              'sphinxcontrib.pecanwsme.rest',
              'wsmeext.sphinxext',
              'openstackdocstheme',
              ]

wsme_protocols = ['restjson']

# autodoc generation is a bit aggressive and a nuisance when doing heavy
# text edit cycles.
# execute "export SPHINX_DEBUG=1" in your terminal to disable

# Add any paths that contain templates here, relative to this directory.
templates_path = ['_templates']

# The suffix of source filenames.
source_suffix = '.rst'

# The master toctree document.
master_doc = 'index'

# General information about the project.
project = u'Ironic Python Agent'
copyright = u'OpenStack Foundation'

# The version info for the project you're documenting, acts as replacement for
# |version| and |release|, also used in various other places throughout the
# built documents.
#
# The short X.Y version.
from ironic_python_agent import version as ipa_version
# The full version, including alpha/beta/rc tags.
release = ipa_version.version_info.release_string()
# The short X.Y version.
version = ipa_version.version_info.version_string()

# A list of ignored prefixes for module index sorting.
modindex_common_prefix = ['ironic_python_agent']

# If true, '()' will be appended to :func: etc. cross-reference text.
add_function_parentheses = True

# If true, the current module name will be prepended to all description
# unit titles (such as .. function::).
add_module_names = True

# The name of the Pygments (syntax highlighting) style to use.
pygments_style = 'sphinx'

# Ignore the following warning: WARNING: while setting up extension
# wsmeext.sphinxext: directive 'autoattribute' is already registered,
# it will be overridden.
suppress_warnings = ['app.add_directive']


# -- Options for HTML output --------------------------------------------------

# The theme to use for HTML and HTML Help pages.  Major themes that come with
# Sphinx are currently 'default' and 'sphinxdoc'.
html_theme = 'openstackdocs'

# openstackdocstheme options
repository_name = 'openstack/ironic-python-agent'
bug_project = 'ironic-python-agent'
bug_tag = ''

# Must set this variable to include year, month, day, hours, and minutes.
html_last_updated_fmt = '%Y-%m-%d %H:%M'

# Output file base name for HTML help builder.
htmlhelp_basename = '%sdoc' % project


# Grouping the document tree into LaTeX files. List of tuples
# (source start file, target name, title, author, documentclass
# [howto/manual]).
latex_documents = [
    (
        'index',
        '%s.tex' % project,
        u'%s Documentation' % project,
        u'OpenStack Foundation',
        'manual'
    ),
]
