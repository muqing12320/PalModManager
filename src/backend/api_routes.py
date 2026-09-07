"""Flask API routes for PalModManager backend."""
from __future__ import annotations

import json
import os
import queue
import sys
import threading
from pathlib import Path

from flask import Blueprint, Response, jsonify, request, stream_with_context

from ..core.models import ModStatus
from ..utils.config import AppConfig
from ..utils.helpers import (
    find_palworld_installation, find_palserver_installation,
    is_valid_palworld_path, is_valid_palserver_path,
)
from .app_state import get_state


api = Blueprint("api", __name__, url_prefix="/api")


def _serialize_mod(mod):
    """Serialize a ModInfo for JSON response."""
    d = mod.to_dict()
    return d


def _get_manager(mode="game"):
    """Get the appropriate ModManager for the requested mode."""
    state = get_state()
    if mode == "server":
        return state.get_server_manager()
    return state.get_game_manager()


def _path_error(mode="game"):
    """Error text naming the path the requested mode is missing."""
    return "服务器路径未设置" if mode == "server" else "游戏路径未设置"


@api.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "version": "1.2.12"})


@api.route("/config", methods=["GET"])
def get_config():
    state = get_state()
    return jsonify(state.config.to_dict())


@api.route("/config", methods=["POST"])
def set_config():
    data = request.get_json(silent=True) or {}
    state = get_state()
    # Partial updates: absent/null fields must not clear stored values.
    state.config.update({k: v for k, v in data.items() if v is not None})
    return jsonify(state.config.to_dict())


@api.route("/mods", methods=["GET"])
def list_mods():
    mode = request.args.get("mode", "game")
    manager = _get_manager(mode)
    if manager is None:
        return jsonify({"error": _path_error(mode)}), 400
    mods = manager.refresh()
    return jsonify({"mods": [_serialize_mod(m) for m in mods]})


@api.route("/stats", methods=["GET"])
def stats():
    mode = request.args.get("mode", "game")
    manager = _get_manager(mode)
    if manager is None:
        return jsonify({"error": _path_error(mode)}), 400
    mods = manager.refresh()
    total = len(mods)
    enabled = sum(1 for m in mods if m.status == ModStatus.ENABLED)
    disabled = sum(1 for m in mods if m.status == ModStatus.DISABLED)
    conflict = sum(1 for m in mods if m.status == ModStatus.CONFLICT)
    return jsonify({
        "total": total,
        "enabled": enabled,
        "disabled": disabled,
        "conflict": conflict,
    })


@api.route("/mods/<mod_id>/toggle", methods=["POST"])
def toggle_mod(mod_id):
    mode = request.args.get("mode", "game")
    manager = _get_manager(mode)
    if manager is None:
        return jsonify({"error": _path_error(mode)}), 400
    success = manager.toggle_mod(mod_id)
    return jsonify({"success": success, "mod": _serialize_mod(manager.get_mod(mod_id)) if success else None})


@api.route("/mods/enable_all", methods=["POST"])
def enable_all():
    mode = request.args.get("mode", "game")
    manager = _get_manager(mode)
    if manager is None:
        return jsonify({"error": _path_error(mode)}), 400
    count = manager.enable_all()
    return jsonify({"success": True, "count": count})


@api.route("/mods/disable_all", methods=["POST"])
def disable_all():
    mode = request.args.get("mode", "game")
    manager = _get_manager(mode)
    if manager is None:
        return jsonify({"error": _path_error(mode)}), 400
    count = manager.disable_all()
    return jsonify({"success": True, "count": count})


@api.route("/mods/<mod_id>", methods=["DELETE"])
def uninstall_mod(mod_id):
    mode = request.args.get("mode", "game")
    manager = _get_manager(mode)
    if manager is None:
        return jsonify({"error": _path_error(mode)}), 400
    mod = manager.get_mod(mod_id)
    if mod is None:
        return jsonify({"error": "Mod 不存在"}), 404
    success = manager.uninstall_mod(mod_id)
    if not success:
        return jsonify({"error": "卸载失败"}), 500
    return jsonify({
        "success": True,
        "backup_error": manager.last_backup_error or "",
    })


@api.route("/mods/import", methods=["POST"])
def import_mod():
    data = request.get_json(silent=True) or {}
    source_path = data.get("source_path")
    mode = data.get("mode", "game")
    if not source_path or not Path(source_path).exists():
        return jsonify({"error": "导入源不存在"}), 400
    manager = _get_manager(mode)
    if manager is None:
        return jsonify({"error": _path_error(mode)}), 400
    mod = manager.install_mod(source_path)
    if mod is None:
        return jsonify({"error": "导入失败：无法识别该 Mod 或写入目标目录出错"}), 500
    return jsonify({"success": True, "mod": _serialize_mod(mod)})


@api.route("/mods/export", methods=["POST"])
def export_mod():
    data = request.get_json(silent=True) or {}
    mode = data.get("mode", "game")
    output_dir = data.get("output_dir")
    if not output_dir:
        return jsonify({"error": "输出目录不能为空"}), 400
    manager = _get_manager(mode)
    if manager is None:
        return jsonify({"error": _path_error(mode)}), 400
    try:
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        count, errors = manager.export_mod_pack(output_dir)
        return jsonify({
            "success": True,
            "count": count,
            "path": str(Path(output_dir) / "Pal"),
            "errors": errors,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api.route("/collection/scan", methods=["POST"])
def scan_collection():
    # Neither ModManager nor ModScanner can enumerate a collection directory
    # (ModScanner paths are tied to a validated game install), so report that
    # instead of returning an empty list the frontend would read as "no mods".
    return jsonify({"error": "合集扫描暂未实现，请使用「导入」逐个安装 Mod"}), 501


@api.route("/frameworks/status", methods=["GET"])
def frameworks_status():
    from ..services.framework_setup import FrameworkSetupService
    mode = request.args.get("mode", "game")
    manager = _get_manager(mode)
    if manager is None:
        return jsonify({"error": _path_error(mode)}), 400
    service = FrameworkSetupService(str(manager.game_dir))
    status = service.get_status()
    return jsonify(status)


@api.route("/frameworks/setup", methods=["POST"])
def frameworks_setup():
    from ..services.framework_setup import FrameworkSetupService
    mode = request.args.get("mode", "game")
    manager = _get_manager(mode)
    if manager is None:
        return jsonify({"error": _path_error(mode)}), 400
    service = FrameworkSetupService(str(manager.game_dir))
    try:
        all_ok, messages = service.setup_all()
        return jsonify({"success": all_ok, "messages": messages})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api.route("/profiles", methods=["GET"])
def list_profiles():
    mode = request.args.get("mode", "game")
    manager = _get_manager(mode)
    if manager is None:
        return jsonify({"profiles": []})
    return jsonify({"profiles": [p.to_dict() for p in manager.get_profiles()]})


@api.route("/profiles", methods=["POST"])
def create_profile():
    data = request.get_json(silent=True) or {}
    name = data.get("name")
    description = data.get("description", "")
    mode = request.args.get("mode", "game")
    if not name:
        return jsonify({"error": "名称不能为空"}), 400
    manager = _get_manager(mode)
    if manager is None:
        return jsonify({"error": _path_error(mode)}), 400
    # save_profile snapshots the currently loaded mods, so scan first.
    manager.refresh()
    profile = manager.save_profile(name, description)
    return jsonify({"success": True, "profile": profile.to_dict()})


@api.route("/profiles/<name>/load", methods=["POST"])
def load_profile(name):
    mode = request.args.get("mode", "game")
    manager = _get_manager(mode)
    if manager is None:
        return jsonify({"error": _path_error(mode)}), 400
    success = manager.load_profile(name)
    return jsonify({"success": success})


@api.route("/profiles/<name>", methods=["DELETE"])
def delete_profile(name):
    mode = request.args.get("mode", "game")
    manager = _get_manager(mode)
    if manager is None:
        return jsonify({"error": _path_error(mode)}), 400
    success = manager.delete_profile(name)
    return jsonify({"success": success})


@api.route("/sync/client_to_server", methods=["POST"])
def sync_client_to_server():
    state = get_state()
    client = state.get_game_manager()
    server = state.get_server_manager()
    if not client or not server:
        return jsonify({"error": "客户端和服务器路径都需要设置"}), 400
    try:
        client.refresh()  # sync_mods_to copies from the cached mod list
        copied, failed, errors = client.sync_mods_to(str(server.game_dir))
        return jsonify({"copied": copied, "failed": failed, "errors": errors})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api.route("/sync/server_to_client", methods=["POST"])
def sync_server_to_client():
    state = get_state()
    client = state.get_game_manager()
    server = state.get_server_manager()
    if not client or not server:
        return jsonify({"error": "客户端和服务器路径都需要设置"}), 400
    try:
        server.refresh()  # sync_mods_to copies from the cached mod list
        copied, failed, errors = server.sync_mods_to(str(client.game_dir))
        return jsonify({"copied": copied, "failed": failed, "errors": errors})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api.route("/game/detect", methods=["GET"])
def detect_game_path():
    path = find_palworld_installation()
    return jsonify({"path": path, "valid": bool(path) and is_valid_palworld_path(path)})


@api.route("/server/detect", methods=["GET"])
def detect_server_path():
    path = find_palserver_installation()
    return jsonify({"path": path, "valid": bool(path) and is_valid_palserver_path(path)})


@api.route("/game/launch", methods=["POST"])
def launch_game():
    from ..utils.helpers import launch_game as _launch_game, launch_palserver
    data = request.get_json(silent=True) or {}
    mode = data.get("mode", "game")
    manager = _get_manager(mode)
    if manager is None:
        return jsonify({"error": _path_error(mode)}), 400
    try:
        path = str(manager.game_dir)
        if mode == "server":
            success, msg = launch_palserver(path)
        else:
            success, msg = _launch_game(path)
        return jsonify({"success": success, "message": msg})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api.route("/repair", methods=["POST"])
def repair_mods():
    mode = request.args.get("mode", "game")
    manager = _get_manager(mode)
    if manager is None:
        return jsonify({"error": _path_error(mode)}), 400
    try:
        fixed, messages = manager.check_and_repair()
        return jsonify({"success": True, "fixed": fixed, "messages": messages})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api.route("/backups", methods=["GET"])
def list_backups():
    manager = _get_manager("game")
    if manager is None:
        return jsonify({"backups": []})
    try:
        backups = manager.list_backups()
        return jsonify({"backups": backups})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api.route("/backups/<backup_id>/restore", methods=["POST"])
def restore_backup(backup_id):
    manager = _get_manager("game")
    if manager is None:
        return jsonify({"error": "路径未设置"}), 400
    try:
        success, msg = manager.restore_backup(backup_id)
        return jsonify({"success": success, "message": msg})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api.route("/update/check", methods=["GET"])
def check_update():
    from ..utils.updater import CURRENT_VERSION, UPDATE_URL, check_for_update
    try:
        info, err = check_for_update(UPDATE_URL)
        if err:
            return jsonify({"error": err}), 500
        # An empty "update" means already on the newest version.
        return jsonify({
            "current_version": CURRENT_VERSION,
            "update": info or {},
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api.route("/update/download-stream", methods=["GET"])
def download_update_stream():
    from ..utils.updater import download_update, UPDATE_URL, check_for_update

    def generate():
        q = queue.Queue()

        def _progress(done, total):
            q.put(("progress", done, total))

        def _method_cb(method):
            q.put(("method", method))

        def _worker():
            try:
                info, err = check_for_update(UPDATE_URL)
                if err or not info:
                    q.put(("error", err or "未找到可用更新"))
                    return
                dl_url = info.get("download_url", "")
                if not dl_url:
                    q.put(("error", "更新信息中缺少下载地址"))
                    return
                saved = download_update(
                    dl_url,
                    progress=_progress,
                    cancel_check=lambda: False,
                    method_cb=_method_cb,
                )
                if saved:
                    q.put(("done", saved))
                else:
                    q.put(("error", "下载未完成，请检查网络或稍后重试"))
            except Exception as e:
                q.put(("error", str(e)))

        threading.Thread(target=_worker, daemon=True).start()

        while True:
            item = q.get()
            kind = item[0]
            if kind == "progress":
                payload = json.dumps({"type": "progress", "done": item[1], "total": item[2]})
            elif kind == "method":
                payload = json.dumps({"type": "method", "text": item[1]})
            elif kind == "done":
                payload = json.dumps({"type": "done", "path": item[1] or ""})
            elif kind == "error":
                payload = json.dumps({"type": "error", "message": item[1]})
            else:
                continue
            yield f"data: {payload}\n\n"
            if kind in ("done", "error"):
                break

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
