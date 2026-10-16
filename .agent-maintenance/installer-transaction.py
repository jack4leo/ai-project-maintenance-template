#!/usr/bin/env python3
"""Descriptor-relative file operations and conservative rollback for install.sh."""

import base64
import hashlib
import json
import os
import secrets
import stat
import sys
import time
from pathlib import Path


class InstallError(Exception):
    pass


DIR_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
NOFOLLOW = getattr(os, "O_NOFOLLOW", None)
if NOFOLLOW is None:
    raise SystemExit("ERROR: this platform cannot safely reject symbolic-link paths.")


def fail(message, status=3):
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(status)


def open_root(root):
    root = os.path.abspath(root)
    fd = os.open("/", DIR_FLAGS)
    try:
        for component in (part for part in root.split("/") if part):
            next_fd = os.open(component, DIR_FLAGS | NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd
    except Exception:
        os.close(fd)
        raise


def load_state(filename):
    try:
        with open(filename, encoding="utf-8") as handle:
            state = json.load(handle)
    except FileNotFoundError:
        state = {"operations": [], "created_directories": []}
    if not isinstance(state, dict):
        raise InstallError("transaction journal is not a JSON object")
    state.setdefault("operations", [])
    state.setdefault("created_directories", [])
    return state


def save_state(filename, state):
    temporary = f"{filename}.tmp-{os.getpid()}-{secrets.token_hex(4)}"
    try:
        with open(temporary, "x", encoding="utf-8") as handle:
            json.dump(state, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, filename)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def split_relative(relative):
    if not relative or relative.startswith("/"):
        raise InstallError(f"unsafe target path: {relative!r}")
    parts = relative.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise InstallError(f"unsafe target path: {relative!r}")
    return parts


def open_parent(root_fd, relative, create, state, state_path):
    parts = split_relative(relative)
    fd = os.dup(root_fd)
    walked = []
    try:
        for component in parts[:-1]:
            walked.append(component)
            try:
                next_fd = os.open(component, DIR_FLAGS | NOFOLLOW, dir_fd=fd)
            except FileNotFoundError:
                if not create:
                    raise
                os.mkdir(component, 0o777, dir_fd=fd)
                state["created_directories"].append("/".join(walked))
                save_state(state_path, state)
                next_fd = os.open(component, DIR_FLAGS | NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd, parts[-1]
    except Exception:
        os.close(fd)
        raise


def xattrs(fd):
    values = {}
    for name in os.listxattr(fd):
        values[name] = base64.b64encode(os.getxattr(fd, name)).decode("ascii")
    return values


def identity(fd):
    before = os.fstat(fd)
    if not stat.S_ISREG(before.st_mode):
        raise InstallError("destination is not a regular file")
    os.lseek(fd, 0, os.SEEK_SET)
    digest = hashlib.sha256()
    while True:
        chunk = os.read(fd, 1024 * 1024)
        if not chunk:
            break
        digest.update(chunk)
    after = os.fstat(fd)
    stable = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_mode", "st_uid", "st_gid")
    if any(getattr(before, name) != getattr(after, name) for name in stable):
        raise InstallError("file changed while it was being inspected")
    if after.st_atime_ns != before.st_atime_ns:
        os.utime(fd, ns=(before.st_atime_ns, before.st_mtime_ns))
        after = os.fstat(fd)
    return {
        "device": after.st_dev,
        "inode": after.st_ino,
        "size": after.st_size,
        "mtime_ns": after.st_mtime_ns,
        "mode": stat.S_IMODE(after.st_mode),
        "uid": after.st_uid,
        "gid": after.st_gid,
        "sha256": digest.hexdigest(),
        "xattrs": hashlib.sha256(
            json.dumps(xattrs(fd), sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
    }


def same_identity(left, right):
    return bool(left and right) and all(left.get(key) == right.get(key) for key in (
        "device", "inode", "size", "mtime_ns", "mode", "uid", "gid", "sha256", "xattrs"
    ))


def metadata(fd):
    info = os.fstat(fd)
    return {
        "mode": stat.S_IMODE(info.st_mode),
        "uid": info.st_uid,
        "gid": info.st_gid,
        "atime_ns": info.st_atime_ns,
        "mtime_ns": info.st_mtime_ns,
        "xattrs": xattrs(fd),
    }


def read_open_file(fd, preserve_times=True):
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode):
        raise InstallError("settings path is not a regular file")
    os.lseek(fd, 0, os.SEEK_SET)
    chunks = []
    while True:
        chunk = os.read(fd, 1024 * 1024)
        if not chunk:
            break
        chunks.append(chunk)
    data = b"".join(chunks)
    if preserve_times:
        os.utime(fd, ns=(info.st_atime_ns, info.st_mtime_ns))
    return data


def open_existing(parent_fd, name, reject_hardlinks=True):
    try:
        info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(info.st_mode):
        raise InstallError("destination is a symbolic link")
    if not stat.S_ISREG(info.st_mode):
        raise InstallError("destination is not a regular file")
    fd = os.open(name, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | NOFOLLOW | getattr(os, "O_NONBLOCK", 0), dir_fd=parent_fd)
    if reject_hardlinks and os.fstat(fd).st_nlink > 1:
        os.close(fd)
        raise InstallError("atomic replacement would break hard links")
    return fd


def inspect_existing(parent_fd, name, allow_hardlinks=False):
    fd = open_existing(parent_fd, name, reject_hardlinks=not allow_hardlinks)
    if fd is None:
        return None
    try:
        info = os.fstat(fd)
        data = read_open_file(fd)
        return {
            "data": data,
            "meta": metadata(fd),
            "identity": identity(fd),
            "stat": {
                "device": info.st_dev,
                "inode": info.st_ino,
            "size": info.st_size,
            "mtime_ns": info.st_mtime_ns,
            "nlink": info.st_nlink,
            },
        }
    finally:
        os.close(fd)


def write_backup(filename, data):
    fd = os.open(filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)


def snapshot_existing(parent_fd, name, state_path, op_index, expected=None):
    current = inspect_existing(parent_fd, name)
    if current is None:
        return None
    if expected and not same_identity(current["identity"], expected):
        raise InstallError("destination changed while it was being prepared")
    state_dir = os.path.dirname(state_path)
    backup = os.path.join(state_dir, f"rollback-{op_index}")
    write_backup(backup, current["data"])
    return {"identity": current["identity"], "meta": current["meta"], "backup": backup}


def apply_metadata(fd, values):
    try:
        if (os.fstat(fd).st_uid, os.fstat(fd).st_gid) != (values["uid"], values["gid"]):
            os.fchown(fd, values["uid"], values["gid"])
        os.fchmod(fd, values["mode"])
        wanted = {
            name: base64.b64decode(value)
            for name, value in values.get("xattrs", {}).items()
        }
        for name in os.listxattr(fd):
            if name not in wanted:
                os.removexattr(fd, name)
        for name, value in wanted.items():
            os.setxattr(fd, name, value)
        os.utime(fd, ns=(values["atime_ns"], values["mtime_ns"]))
        info = os.fstat(fd)
        actual = xattrs(fd)
        if (
            (info.st_uid, info.st_gid) != (values["uid"], values["gid"])
            or stat.S_IMODE(info.st_mode) != values["mode"]
            or info.st_atime_ns != values["atime_ns"]
            or info.st_mtime_ns != values["mtime_ns"]
            or actual != values.get("xattrs", {})
        ):
            raise OSError("staged file metadata did not match the original")
    except (OSError, AttributeError, NotImplementedError) as exc:
        raise InstallError(f"could not safely preserve file metadata: {exc}") from exc


def new_temp(parent_fd, name, data, values):
    temporary = f".{name}.flywheel-{os.getpid()}-{secrets.token_hex(6)}"
    fd = os.open(
        temporary,
        os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | NOFOLLOW,
        0o600,
        dir_fd=parent_fd,
    )
    try:
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            view = view[written:]
        apply_metadata(fd, values)
        os.fsync(fd)
        expected = identity(fd)
        os.utime(fd, ns=(values["atime_ns"], values["mtime_ns"]))
        return temporary, fd, expected
    except Exception:
        os.close(fd)
        try:
            os.unlink(temporary, dir_fd=parent_fd)
        except OSError:
            pass
        raise


def source_file(path):
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise InstallError(f"source is not a regular file: {path}")
        data = read_open_file(fd)
        values = {
            "mode": stat.S_IMODE(info.st_mode),
            "uid": info.st_uid,
            "gid": info.st_gid,
            "atime_ns": info.st_atime_ns,
            "mtime_ns": info.st_mtime_ns,
            "xattrs": {},
        }
        return data, values
    finally:
        os.close(fd)


def path_exists(parent_fd, name):
    try:
        os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        return True
    except FileNotFoundError:
        return False


def op_copy(root, relative, source, state_path):
    state = load_state(state_path)
    root_fd = open_root(root)
    parent_fd = None
    temporary = None
    temp_fd = None
    try:
        parent_fd, name = open_parent(root_fd, relative, True, state, state_path)
        if path_exists(parent_fd, name):
            print("EXISTS")
            raise SystemExit(10)
        data, values = source_file(source)
        temporary, temp_fd, expected = new_temp(parent_fd, name, data, values)
        operation = {"path": relative, "existed": False, "expected": expected}
        state["operations"].append(operation)
        save_state(state_path, state)
        try:
            os.link(temporary, name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd, follow_symlinks=False)
        except FileExistsError:
            state["operations"].pop()
            save_state(state_path, state)
            print("EXISTS")
            raise SystemExit(10)
        os.unlink(temporary, dir_fd=parent_fd)
        temporary = None
        print("INSTALLED")
    finally:
        if temp_fd is not None:
            os.close(temp_fd)
        if temporary is not None and parent_fd is not None:
            try:
                os.unlink(temporary, dir_fd=parent_fd)
            except OSError:
                pass
        if parent_fd is not None:
            os.close(parent_fd)
        os.close(root_fd)


def read_stage(path):
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise InstallError("staged file is not regular")
        return read_open_file(fd, preserve_times=False)
    finally:
        os.close(fd)


def check_current(parent_fd, name, expected):
    current = inspect_existing(parent_fd, name)
    if current is None or not same_identity(current["identity"], expected):
        raise InstallError("destination changed concurrently; no replacement was applied")
    return current


def op_replace(root, relative, staged, baseline, state_path):
    state = load_state(state_path)
    root_fd = open_root(root)
    parent_fd = None
    temporary = None
    temp_fd = None
    try:
        parent_fd, name = open_parent(root_fd, relative, False, state, state_path)
        original = inspect_existing(parent_fd, name)
        if original is None:
            raise InstallError("AGENTS.md disappeared before the confirmed update")
        if read_stage(baseline) != original["data"]:
            raise InstallError("AGENTS.md changed while awaiting confirmation; review and retry")
        op_index = len(state["operations"])
        snapshot = snapshot_existing(parent_fd, name, state_path, op_index, original["identity"])
        data = read_stage(staged)
        temporary, temp_fd, expected = new_temp(parent_fd, name, data, snapshot["meta"])
        operation = {
            "path": relative,
            "existed": True,
            "original": snapshot["identity"],
            "backup": snapshot["backup"],
            "meta": snapshot["meta"],
            "expected": expected,
        }
        state["operations"].append(operation)
        save_state(state_path, state)
        check_current(parent_fd, name, snapshot["identity"])
        os.replace(temporary, name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        temporary = None
        print("REPLACED")
    finally:
        if temp_fd is not None:
            os.close(temp_fd)
        if temporary is not None and parent_fd is not None:
            try:
                os.unlink(temporary, dir_fd=parent_fd)
            except OSError:
                pass
        if parent_fd is not None:
            os.close(parent_fd)
        os.close(root_fd)


def validate_config(config, filename):
    if not isinstance(config, dict):
        raise InstallError(f"{filename} must contain a JSON object")
    hooks = config.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise InstallError(f"{filename}: 'hooks' must be a JSON object")
    sessions = hooks.setdefault("SessionStart", [])
    if not isinstance(sessions, list):
        raise InstallError(f"{filename}: 'hooks.SessionStart' must be a JSON array")
    for session in sessions:
        if isinstance(session, dict) and not isinstance(session.get("hooks", []), list):
            raise InstallError(f"{filename}: each SessionStart 'hooks' value must be a JSON array")
    return sessions


def hook_entry(provider):
    if provider == "codex":
        return {
            "matcher": "startup|resume|clear|compact|fork",
            "hooks": [{
                "type": "command",
                "command": 'bash "$(git rev-parse --show-toplevel)/.agent-maintenance/session-start.sh" codex',
                "timeout": 5,
                "additionalContextLimit": 1200,
            }],
        }
    return {
        "matcher": "startup|resume|clear|compact|fork",
        "hooks": [{
            "type": "command",
            "command": 'bash "${CLAUDE_PROJECT_DIR}/.agent-maintenance/session-start.sh" claude',
        }],
    }


def op_merge_hook(root, provider, relative, state_path):
    state = load_state(state_path)
    root_fd = open_root(root)
    parent_fd = None
    temporary = None
    temp_fd = None
    try:
        parent_fd, name = open_parent(root_fd, relative, True, state, state_path)
        original = inspect_existing(parent_fd, name)
        config = {}
        if original is not None:
            try:
                config = json.loads(original["data"].decode("utf-8"))
            except Exception as exc:
                raise InstallError(f"cannot safely parse {relative}: {exc}; no settings were changed") from exc
        sessions = validate_config(config, relative)
        entry = hook_entry(provider)
        command = entry["hooks"][0]["command"]
        for existing in sessions:
            if not isinstance(existing, dict):
                continue
            for handler in existing.get("hooks", []):
                if isinstance(handler, dict) and handler.get("command") == command:
                    print("HOOK PRESENT")
                    return
        sessions.append(entry)
        payload = (json.dumps(config, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        if original is None:
            template = {
                "mode": 0o644,
                "uid": os.geteuid(),
                "gid": os.getegid(),
                "atime_ns": time.time_ns(),
                "mtime_ns": time.time_ns(),
                "xattrs": {},
            }
            backup = None
            old_identity = None
        else:
            if original["stat"]["nlink"] > 1:
                raise InstallError("atomic replacement would break hard links")
            op_index = len(state["operations"])
            snapshot = snapshot_existing(parent_fd, name, state_path, op_index, original["identity"])
            template = snapshot["meta"]
            backup = snapshot["backup"]
            old_identity = snapshot["identity"]
        temporary, temp_fd, expected = new_temp(parent_fd, name, payload, template)
        operation = {
            "path": relative,
            "existed": original is not None,
            "original": old_identity,
            "backup": backup,
            "meta": template if original is not None else None,
            "expected": expected,
        }
        state["operations"].append(operation)
        save_state(state_path, state)
        if old_identity:
            check_current(parent_fd, name, old_identity)
            os.replace(temporary, name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        else:
            if path_exists(parent_fd, name):
                state["operations"].pop()
                save_state(state_path, state)
                raise InstallError(f"{relative} appeared while its hook was being prepared")
            os.link(temporary, name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd, follow_symlinks=False)
            os.unlink(temporary, dir_fd=parent_fd)
        temporary = None
        print("HOOK ADDED")
    finally:
        if temp_fd is not None:
            os.close(temp_fd)
        if temporary is not None and parent_fd is not None:
            try:
                os.unlink(temporary, dir_fd=parent_fd)
            except OSError:
                pass
        if parent_fd is not None:
            os.close(parent_fd)
        os.close(root_fd)


def restore_backup(parent_fd, name, operation):
    with open(operation["backup"], "rb") as handle:
        data = handle.read()
    temporary, fd, _expected = new_temp(parent_fd, name, data, operation["meta"])
    try:
        # link is atomic and does not overwrite an external file that appeared meanwhile.
        os.link(temporary, name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd, follow_symlinks=False)
    finally:
        os.close(fd)
        try:
            os.unlink(temporary, dir_fd=parent_fd)
        except OSError:
            pass


def signature_at(parent_fd, name):
    fd = open_existing(parent_fd, name)
    if fd is None:
        return None
    try:
        return identity(fd)
    finally:
        os.close(fd)


def rollback(root, state_path):
    state = load_state(state_path)
    incomplete = False
    root_fd = open_root(root)
    try:
        for operation in reversed(state["operations"]):
            relative = operation["path"]
            parent_fd = None
            quarantine = None
            try:
                parent_fd, name = open_parent(root_fd, relative, False, state, state_path)
                current = signature_at(parent_fd, name)
                if current is None:
                    if operation["existed"]:
                        print(f"PRESERVED concurrent removal; rollback skipped: {relative}", file=sys.stderr)
                        incomplete = True
                    continue
                if same_identity(current, operation.get("original")) and operation["existed"]:
                    continue
                if not same_identity(current, operation["expected"]):
                    print(f"PRESERVED concurrent change; rollback skipped: {relative}", file=sys.stderr)
                    incomplete = True
                    continue
                # Move the exact installer-produced directory entry aside before undoing it.
                # This prevents an intervening replacement from being blindly unlinked.
                quarantine = f".{name}.rollback-{os.getpid()}-{secrets.token_hex(5)}"
                os.rename(name, quarantine, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
                moved = signature_at(parent_fd, quarantine)
                if not same_identity(moved, operation["expected"]):
                    try:
                        os.link(quarantine, name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd, follow_symlinks=False)
                        os.unlink(quarantine, dir_fd=parent_fd)
                        quarantine = None
                    except OSError:
                        print(f"PRESERVED changed file in recovery path {quarantine}: {relative}", file=sys.stderr)
                    incomplete = True
                    continue
                if operation["existed"]:
                    try:
                        restore_backup(parent_fd, name, operation)
                    except FileExistsError:
                        print(f"PRESERVED concurrent replacement; rollback skipped: {relative}", file=sys.stderr)
                        incomplete = True
                        os.unlink(quarantine, dir_fd=parent_fd)
                        quarantine = None
                        continue
                os.unlink(quarantine, dir_fd=parent_fd)
                quarantine = None
            except FileNotFoundError:
                if operation["existed"]:
                    print(f"PRESERVED missing parent; rollback skipped: {relative}", file=sys.stderr)
                    incomplete = True
            except OSError as exc:
                print(f"ERROR: rollback could not safely process {relative}: {exc}", file=sys.stderr)
                incomplete = True
            except InstallError as exc:
                print(f"ERROR: rollback could not safely process {relative}: {exc}", file=sys.stderr)
                incomplete = True
            finally:
                if quarantine and parent_fd is not None:
                    try:
                        if not path_exists(parent_fd, name):
                            os.link(quarantine, name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd, follow_symlinks=False)
                            os.unlink(quarantine, dir_fd=parent_fd)
                        else:
                            print(f"PRESERVED recovery file {quarantine} in destination directory", file=sys.stderr)
                            incomplete = True
                    except OSError:
                        print(f"PRESERVED recovery file {quarantine} in destination directory", file=sys.stderr)
                        incomplete = True
                if parent_fd is not None:
                    os.close(parent_fd)
        for relative in reversed(state["created_directories"]):
            parent_fd = None
            try:
                parent_fd, name = open_parent(root_fd, relative, False, state, state_path)
                os.rmdir(name, dir_fd=parent_fd)
            except FileNotFoundError:
                pass
            except OSError:
                # Never remove a directory that has become non-empty or unsafe.
                print(f"PRESERVED created directory with concurrent contents: {relative}", file=sys.stderr)
                incomplete = True
            except InstallError as exc:
                print(f"PRESERVED created directory {relative}: {exc}", file=sys.stderr)
                incomplete = True
            finally:
                if parent_fd is not None:
                    os.close(parent_fd)
    finally:
        os.close(root_fd)
    return 1 if incomplete else 0


def snapshot_command(root, relative, output):
    root_fd = open_root(root)
    parent_fd = None
    try:
        state = {"operations": [], "created_directories": []}
        parent_fd, name = open_parent(root_fd, relative, False, state, output + ".state-unused")
        current = inspect_existing(parent_fd, name, allow_hardlinks=True)
        if current is None:
            raise InstallError(f"file is missing: {relative}")
        with open(output, "wb") as handle:
            handle.write(current["data"])
    finally:
        if parent_fd is not None:
            os.close(parent_fd)
        os.close(root_fd)
        try:
            os.unlink(output + ".state-unused")
        except FileNotFoundError:
            pass


def main(argv):
    if not argv:
        fail("missing operation")
    command = argv[0]
    try:
        if command == "init" and len(argv) == 3:
            root_fd = open_root(argv[1])
            os.close(root_fd)
            save_state(argv[2], {"operations": [], "created_directories": []})
        elif command == "snapshot" and len(argv) == 4:
            snapshot_command(argv[1], argv[2], argv[3])
        elif command == "copy" and len(argv) == 5:
            op_copy(argv[1], argv[2], argv[3], argv[4])
        elif command == "replace" and len(argv) == 6:
            op_replace(argv[1], argv[2], argv[3], argv[4], argv[5])
        elif command == "merge-hook" and len(argv) == 5:
            op_merge_hook(argv[1], argv[2], argv[3], argv[4])
        elif command == "rollback" and len(argv) == 3:
            return rollback(argv[1], argv[2])
        else:
            fail(f"invalid operation or arguments: {command}")
    except SystemExit:
        raise
    except (OSError, ValueError, json.JSONDecodeError, InstallError) as exc:
        fail(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
