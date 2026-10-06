"""
Vercel entry point.

Vercel serves whatever WSGI callable this module exposes as `app`. Everything
the request path needs is in `gallery/bundle/`, committed: the deployment holds
no Supabase key and no Notion token, and makes no network call to draw a chart.

    ############################################################################
    ##  THE RENDER PATH STILL exec()s TEMPLATE CODE.                          ##
    ##                                                                        ##
    ##  What makes that defensible here, and did not before, is that the only  ##
    ##  code it can reach is the reviewed set frozen into gallery/bundle/ at   ##
    ##  build time. Nothing is fetched at runtime, so no newly generated       ##
    ##  template can arrive unread. Rebuilding the bundle is the review gate.  ##
    ##                                                                        ##
    ##  It is NOT a sandbox. Before this serves anyone whose data you would    ##
    ##  not run locally, move build_figure into an isolated worker -- separate ##
    ##  process, no network, no filesystem, hard timeout.                      ##
    ############################################################################
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# The bundle's vendored copy comes first: a deployment ships no Scripts/ at all,
# and locally this keeps the app running against the same modules that were
# frozen rather than whichever version is in the working tree.
sys.path.insert(0, os.path.join(_ROOT, "gallery"))
sys.path.insert(0, os.path.join(_ROOT, "Scripts", "lib"))
sys.path.insert(0, os.path.join(_ROOT, "gallery", "bundle", "lib"))

try:
    from app import app  # noqa: E402,F401
except Exception:
    # A failed import here is otherwise invisible: the platform answers 500
    # FUNCTION_INVOCATION_FAILED with no clue which module was missing, and the
    # first two deploys were each spent guessing. Report it instead.
    import json
    import traceback

    _TRACE = traceback.format_exc()
    _DIAG = {
        "error": "the application failed to import",
        "traceback": _TRACE.splitlines(),
        "python": sys.version,
        "cwd": os.getcwd(),
        "root": _ROOT,
        "root_listing": sorted(os.listdir(_ROOT))[:40] if os.path.isdir(_ROOT) else None,
        "gallery_listing": sorted(os.listdir(os.path.join(_ROOT, "gallery")))[:40]
            if os.path.isdir(os.path.join(_ROOT, "gallery")) else "gallery/ is NOT present",
        "bundle_lib": sorted(os.listdir(os.path.join(_ROOT, "gallery", "bundle", "lib")))
            if os.path.isdir(os.path.join(_ROOT, "gallery", "bundle", "lib"))
            else "gallery/bundle/lib/ is NOT present",
        "sys_path": sys.path,
    }
    print(_TRACE)

    def app(environ, start_response):                 # minimal WSGI diagnostic
        body = json.dumps(_DIAG, indent=1).encode()
        start_response("500 Internal Server Error",
                       [("Content-Type", "application/json"), ("Content-Length", str(len(body)))])
        return [body]
