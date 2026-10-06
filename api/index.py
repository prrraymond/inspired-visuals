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
sys.path.insert(0, os.path.join(_ROOT, "gallery"))
sys.path.insert(0, os.path.join(_ROOT, "Scripts", "lib"))

from app import app  # noqa: E402,F401
