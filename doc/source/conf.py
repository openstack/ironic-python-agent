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
copyright = u'OpenStack Foundation'

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

# Output file base name for HTML help builder.
htmlhelp_basename = 'Ironic Python Agentdoc' 

latex_use_xindy = False

# Grouping the document tree into LaTeX files. List of tuples
# (source start file, target name, title, author, documentclass
# [howto/manual]).
latex_documents = [
    (
        'index',
        'doc-ironic-python-agent.tex',
        u'Ironic Python Agent Documentation',
        u'OpenStack Foundation',
        'manual'
    ),
]
