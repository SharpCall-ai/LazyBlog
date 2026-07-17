"""LazyBlog — a topic goes in a sheet, a markdown post comes out, it gets POSTed to your site.

LazyBlog renders no HTML, serves no API and opens no port. The entire contract with
the outside world is one signed HTTP POST carrying markdown; what happens to that
markdown is the receiver's business.
"""

__version__ = "0.1.0"


class LazyBlogError(Exception):
    """Anything the user can fix: bad config, missing secret, LLM or delivery failure."""
