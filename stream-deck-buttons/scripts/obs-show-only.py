#!/usr/bin/env python3
"""Show exactly one OBS scene item from a group and hide the rest (or hide all with --show off).

Needs OBS running with obs-websocket v5 and `pip install websocket-client`.
Port and password come from OBS's own config file; nothing secret is passed on the command line.

  obs-show-only.py --scene "My Scene" --list
  obs-show-only.py --scene "My Scene" --group 31,32,33 --show 32
  obs-show-only.py --scene "My Scene" --group 31,32,33 --show off
"""
import argparse
import base64
import hashlib
import json
import os
import sys

CONFIG = os.path.expanduser(
    "~/Library/Application Support/obs-studio/plugin_config/obs-websocket/config.json")


def connect():
    try:
        import websocket  # websocket-client
    except ImportError:
        sys.exit("install the client first: pip3 install websocket-client")
    cfg = {}
    if os.path.isfile(CONFIG):
        with open(CONFIG) as f:
            cfg = json.load(f)
    ws = websocket.create_connection("ws://127.0.0.1:%s" % cfg.get("server_port", 4455), timeout=8)
    hello = json.loads(ws.recv())["d"]
    ident = {"rpcVersion": hello.get("rpcVersion", 1)}
    if "authentication" in hello:
        auth = hello["authentication"]
        pw = cfg.get("server_password", "")
        secret = base64.b64encode(hashlib.sha256((pw + auth["salt"]).encode()).digest()).decode()
        ident["authentication"] = base64.b64encode(
            hashlib.sha256((secret + auth["challenge"]).encode()).digest()).decode()
    ws.send(json.dumps({"op": 1, "d": ident}))
    if json.loads(ws.recv()).get("op") != 2:
        sys.exit("obs-websocket refused the login; check the password in OBS settings")
    return ws


def request(ws, counter, kind, data=None):
    counter[0] += 1
    rid = "r%d" % counter[0]
    ws.send(json.dumps({"op": 6, "d": {"requestType": kind, "requestId": rid,
                                        "requestData": data or {}}}))
    while True:
        msg = json.loads(ws.recv())
        if msg.get("op") == 7 and msg["d"].get("requestId") == rid:
            status = msg["d"].get("requestStatus", {})
            if not status.get("result", False):
                sys.exit("OBS said no to %s: %s" % (kind, status.get("comment", status)))
            return msg["d"].get("responseData") or {}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scene", required=True)
    ap.add_argument("--list", action="store_true", help="print scene-item ids and names")
    ap.add_argument("--group", help="comma-separated scene-item ids that act as one set")
    ap.add_argument("--show", help="the id to show, or 'off' to hide the whole group")
    a = ap.parse_args()
    ws, counter = connect(), [0]
    try:
        if a.list:
            items = request(ws, counter, "GetSceneItemList", {"sceneName": a.scene})
            for it in items.get("sceneItems", []):
                print("%-5s %-6s %s" % (it["sceneItemId"],
                                        "on" if it.get("sceneItemEnabled") else "off",
                                        it.get("sourceName")))
            return
        if not a.group or not a.show:
            sys.exit("need --group and --show (or --list)")
        group = [int(x) for x in a.group.split(",") if x.strip()]
        target = None if a.show.lower() == "off" else int(a.show)
        if target is not None and target not in group:
            sys.exit("--show %s is not in --group" % target)
        for sid in group:
            request(ws, counter, "SetSceneItemEnabled",
                    {"sceneName": a.scene, "sceneItemId": sid, "sceneItemEnabled": sid == target})
        print("showing %s" % (target if target is not None else "nothing"))
    finally:
        ws.close()


if __name__ == "__main__":
    main()
