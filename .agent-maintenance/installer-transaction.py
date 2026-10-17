#!/usr/bin/env python3
"""Descriptor-relative file operations and conservative rollback for install.sh."""

import base64
import ctypes
import errno
import fcntl
import hashlib
import json
import os
import re
import secrets
import stat
import sys
import time


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
                try:
                    save_state(state_path, state)
                except Exception:
                    print(
                        f"PRESERVED directory created before transaction journal failure; rollback was incomplete because it was not removed safely: {'/'.join(walked)}",
                        file=sys.stderr,
                    )
                    raise
                next_fd = os.open(component, DIR_FLAGS | NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd, parts[-1]
    except Exception:
        os.close(fd)
        raise


def verify_parent(root, root_fd, relative, parent_fd):
    """Re-resolve the project path and ensure the held parent is still beneath it."""
    current_fd = None
    parent_check_fd = None
    try:
        current_fd = open_root(root)
        root_info = os.fstat(root_fd)
        current_root_info = os.fstat(current_fd)
        if (root_info.st_dev, root_info.st_ino) != (current_root_info.st_dev, current_root_info.st_ino):
            return False
        parent_check_fd = os.dup(current_fd)
        for component in split_relative(relative)[:-1]:
            next_fd = os.open(component, DIR_FLAGS | NOFOLLOW, dir_fd=parent_check_fd)
            os.close(parent_check_fd)
            parent_check_fd = next_fd
        expected = os.fstat(parent_fd)
        actual = os.fstat(parent_check_fd)
        return (expected.st_dev, expected.st_ino) == (actual.st_dev, actual.st_ino)
    except (OSError, InstallError):
        return False
    finally:
        if parent_check_fd is not None:
            os.close(parent_check_fd)
        if current_fd is not None:
            os.close(current_fd)


def rename_noreplace(parent_fd, source, destination):
    """Move an entry only if the recovery name is still absent; fail closed if unavailable."""
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        function_name, flag = "renameatx_np", 0x00000004  # RENAME_EXCL
    elif sys.platform.startswith("linux"):
        function_name, flag = "renameat2", 0x00000001  # RENAME_NOREPLACE
    else:
        raise InstallError("this platform has no supported atomic no-replace rename for rollback")
    try:
        function = getattr(libc, function_name)
    except AttributeError as exc:
        raise InstallError("atomic no-replace rename is unavailable; rollback left the file in place") from exc
    function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    function.restype = ctypes.c_int
    result = function(parent_fd, os.fsencode(source), parent_fd, os.fsencode(destination), flag)
    if result != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), destination)


def xattrs(fd):
    listxattr = getattr(os, "listxattr", None)
    getxattr = getattr(os, "getxattr", None)
    if not callable(listxattr) or not callable(getxattr):
        return None
    values = {}
    for name in listxattr(fd):
        values[name] = base64.b64encode(getxattr(fd, name)).decode("ascii")
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
    attributes = xattrs(fd)
    return {
        "device": after.st_dev,
        "inode": after.st_ino,
        "size": after.st_size,
        "mtime_ns": after.st_mtime_ns,
        "mode": stat.S_IMODE(after.st_mode),
        "uid": after.st_uid,
        "gid": after.st_gid,
        "sha256": digest.hexdigest(),
        "xattrs": None if attributes is None else hashlib.sha256(
            json.dumps(attributes, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
    }


def same_identity(left, right):
    # Without xattr inspection, a matching inode/content signature is not
    # enough evidence to remove a recovery candidate during rollback.
    if not left or not right or left.get("xattrs") is None or right.get("xattrs") is None:
        return False
    return all(left.get(key) == right.get(key) for key in (
        "device", "inode", "size", "mtime_ns", "mode", "uid", "gid", "sha256", "xattrs"
    ))


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
    if preserve_times and os.fstat(fd).st_atime_ns != info.st_atime_ns:
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
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | NOFOLLOW | getattr(os, "O_NONBLOCK", 0)
    noatime = getattr(os, "O_NOATIME", 0)
    try:
        fd = os.open(name, flags | noatime, dir_fd=parent_fd)
    except OSError as exc:
        if not noatime or exc.errno not in {errno.EPERM, errno.EINVAL, errno.EOPNOTSUPP, errno.ENOTSUP}:
            raise
        fd = os.open(name, flags, dir_fd=parent_fd)
    if reject_hardlinks and os.fstat(fd).st_nlink > 1:
        os.close(fd)
        raise InstallError("destination has multiple hard links; refusing to modify it")
    return fd


def inspect_existing(parent_fd, name, allow_hardlinks=False):
    fd = open_existing(parent_fd, name, reject_hardlinks=not allow_hardlinks)
    if fd is None:
        return None
    try:
        data = read_open_file(fd)
        return {"data": data, "nlink": os.fstat(fd).st_nlink}
    finally:
        os.close(fd)


def apply_metadata(fd, values):
    try:
        if (os.fstat(fd).st_uid, os.fstat(fd).st_gid) != (values["uid"], values["gid"]):
            os.fchown(fd, values["uid"], values["gid"])
        os.fchmod(fd, values["mode"])
        wanted = {
            name: base64.b64decode(value)
            for name, value in values.get("xattrs", {}).items()
        }
        listxattr = getattr(os, "listxattr", None)
        getxattr = getattr(os, "getxattr", None)
        removexattr = getattr(os, "removexattr", None)
        setxattr = getattr(os, "setxattr", None)
        xattr_api = all(callable(function) for function in (listxattr, getxattr, removexattr, setxattr))
        if xattr_api:
            for name in listxattr(fd):
                if name not in wanted:
                    removexattr(fd, name)
            for name, value in wanted.items():
                setxattr(fd, name, value)
            actual = xattrs(fd)
        elif wanted:
            raise NotImplementedError("xattr APIs are unavailable for requested file attributes")
        else:
            # A new transaction-owned staging file requests no xattrs; core
            # mode/owner/time metadata can still be applied safely.
            actual = None
        os.utime(fd, ns=(values["atime_ns"], values["mtime_ns"]))
        info = os.fstat(fd)
        if (
            (info.st_uid, info.st_gid) != (values["uid"], values["gid"])
            or stat.S_IMODE(info.st_mode) != values["mode"]
            or info.st_atime_ns != values["atime_ns"]
            or info.st_mtime_ns != values["mtime_ns"]
            or (actual is not None and actual != values.get("xattrs", {}))
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
    fd = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0) | NOFOLLOW,
    )
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


def compare_command(root, relative, source):
    """Compare regular files through pinned descriptors without FIFO blocking."""
    source_fd = None
    root_fd = open_root(root)
    parent_fd = None
    destination_fd = None
    try:
        source_fd = os.open(
            source,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0) | NOFOLLOW,
        )
        source_info = os.fstat(source_fd)
        if not stat.S_ISREG(source_info.st_mode):
            raise InstallError(f"source is not a regular file: {source}")
        parent_fd, name = open_parent(root_fd, relative, False, {"created_directories": []}, "")
        destination_fd = open_existing(parent_fd, name, reject_hardlinks=False)
        if destination_fd is None:
            return 1
        destination_info = os.fstat(destination_fd)
        if not stat.S_ISREG(destination_info.st_mode):
            raise InstallError(f"destination is not a regular file: {relative}")
        os.lseek(source_fd, 0, os.SEEK_SET)
        os.lseek(destination_fd, 0, os.SEEK_SET)
        while True:
            source_chunk = os.read(source_fd, 1024 * 1024)
            destination_chunk = os.read(destination_fd, 1024 * 1024)
            if source_chunk != destination_chunk:
                return 1
            if not source_chunk:
                break
        if (os.fstat(source_fd).st_size != source_info.st_size or
                os.fstat(destination_fd).st_size != destination_info.st_size):
            raise InstallError(f"file changed while being compared: {relative}")
        return 0
    finally:
        if destination_fd is not None:
            os.close(destination_fd)
        if parent_fd is not None:
            os.close(parent_fd)
        os.close(root_fd)
        if source_fd is not None:
            os.close(source_fd)


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
        if not verify_parent(root, root_fd, relative, parent_fd):
            raise InstallError(f"target directory moved or changed after it was opened; refusing write: {relative}")
        if path_exists(parent_fd, name):
            print("EXISTS")
            raise SystemExit(10)
        data, values = source_file(source)
        if not verify_parent(root, root_fd, relative, parent_fd):
            raise InstallError(f"target directory moved or changed before staging: {relative}")
        temporary, temp_fd, expected = new_temp(parent_fd, name, data, values)
        operation = {"path": relative, "expected": expected}
        state["operations"].append(operation)
        save_state(state_path, state)
        if not verify_parent(root, root_fd, relative, parent_fd):
            raise InstallError(f"target directory moved or changed before publishing; staged file was not installed: {relative}")
        try:
            os.link(temporary, name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd, follow_symlinks=False)
        except FileExistsError:
            state["operations"].pop()
            save_state(state_path, state)
            print("EXISTS")
            raise SystemExit(10)
        if not verify_parent(root, root_fd, relative, parent_fd):
            print(f"PRESERVED file written through a directory moved during publication: {relative}", file=sys.stderr)
            raise InstallError(f"target directory moved during publication; rollback will preserve uncertain data: {relative}")
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
        if not isinstance(session, dict):
            raise InstallError(f"{filename}: each SessionStart entry must be a JSON object")
        if "matcher" in session and not isinstance(session["matcher"], str):
            raise InstallError(f"{filename}: each SessionStart matcher must be a string")
        handlers = session.get("hooks")
        if not isinstance(handlers, list):
            raise InstallError(f"{filename}: each SessionStart 'hooks' value must be a JSON array")
        for handler in handlers:
            if not isinstance(handler, dict) or not isinstance(handler.get("type"), str):
                raise InstallError(f"{filename}: each SessionStart hook must be an object with a string 'type'")
            if handler["type"] == "command" and not isinstance(handler.get("command"), str):
                raise InstallError(f"{filename}: each command SessionStart hook must have a string 'command'")
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


def hook_matches_all_session_sources(session):
    matcher = session.get("matcher")
    return "matcher" not in session or matcher in (
        "",
        "*",
        ".*",
        "startup|resume|clear|compact|fork",
    )


def hook_is_registered(provider, sessions):
    command = hook_entry(provider)["hooks"][0]["command"]
    return any(
        isinstance(session, dict)
        and hook_matches_all_session_sources(session)
        and any(
            isinstance(handler, dict)
            and handler.get("type") == "command"
            and handler.get("command") == command
            for handler in session.get("hooks", [])
        )
        for session in sessions
    )


LOCK_FD_ENV = "SELF_EVOLUTION_FLYWHEEL_LOCK_FD"
HOOK_SETTINGS = {
    "codex": ".codex/hooks.json",
    "claude": ".claude/settings.json",
}


def acquire_target_lock(root):
    fd = open_root(root)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        os.close(fd)
        raise InstallError("another installer is active for this target; retry after it exits") from exc
    except OSError as exc:
        os.close(fd)
        raise InstallError(f"cannot acquire an exclusive target lock: {exc}") from exc
    return fd


def verify_target_lock(root, descriptor):
    try:
        fd = int(descriptor)
        held = os.fstat(fd)
        if not stat.S_ISDIR(held.st_mode):
            raise InstallError("installer lock descriptor is not a directory")
        root_fd = open_root(root)
        try:
            actual = os.fstat(root_fd)
        finally:
            os.close(root_fd)
        if (held.st_dev, held.st_ino) != (actual.st_dev, actual.st_ino):
            raise InstallError("installer lock descriptor does not match the target directory")
        # Reasserting flock on the inherited open-file description is safe; if
        # this descriptor was not locked by the launcher, it locks it here.
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except InstallError:
        raise
    except (OSError, ValueError) as exc:
        raise InstallError(f"installer target lock is missing or invalid: {exc}") from exc


def lock_and_exec(root, command):
    if not command:
        raise InstallError("target lock launcher requires a command")
    fd = acquire_target_lock(root)
    os.set_inheritable(fd, True)
    env = os.environ.copy()
    env[LOCK_FD_ENV] = str(fd)
    os.execvpe(command[0], command, env)


def expected_new_hook_payload(provider):
    config = {}
    sessions = validate_config(config, HOOK_SETTINGS[provider])
    sessions.append(hook_entry(provider))
    return (json.dumps(config, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def recover_provider_staging(root, provider, report=True):
    if provider not in HOOK_SETTINGS:
        raise InstallError(f"unknown provider: {provider}")
    descriptor = os.environ.get(LOCK_FD_ENV)
    if descriptor is None:
        raise InstallError("refusing staging recovery without the exclusive target lock")
    verify_target_lock(root, descriptor)

    relative = HOOK_SETTINGS[provider]
    state = {"operations": [], "created_directories": []}
    root_fd = open_root(root)
    parent_fd = None
    try:
        try:
            parent_fd, name = open_parent(root_fd, relative, False, state, "")
        except FileNotFoundError:
            return False
        if not verify_parent(root, root_fd, relative, parent_fd):
            raise InstallError(f"target directory moved or changed during staging recovery: {relative}")

        prefix = f".{name}.flywheel-"
        matching = [entry for entry in os.listdir(parent_fd) if entry.startswith(prefix)]
        if not matching:
            return False
        pattern = re.compile(rf"\.{re.escape(name)}\.flywheel-[0-9]+-[0-9a-f]{{12}}\Z")
        unknown = [entry for entry in matching if pattern.fullmatch(entry) is None]
        if unknown:
            raise InstallError(
                f"unrecognized possible provider staging entry for {relative}: {unknown[0]}; left untouched"
            )
        if len(matching) != 1:
            raise InstallError(f"multiple possible provider staging entries for {relative}; left untouched")
        alias = matching[0]

        try:
            active_info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError as exc:
            raise InstallError(f"staging entry {alias} has no unique active settings file {relative}; left untouched") from exc
        alias_info = os.stat(alias, dir_fd=parent_fd, follow_symlinks=False)
        if not stat.S_ISREG(active_info.st_mode) or not stat.S_ISREG(alias_info.st_mode):
            raise InstallError(f"possible provider staging entry {alias} is not a regular file; left untouched")
        if (active_info.st_dev, active_info.st_ino) != (alias_info.st_dev, alias_info.st_ino):
            raise InstallError(f"possible provider staging entry {alias} is not the active settings inode; left untouched")
        if active_info.st_nlink != 2 or alias_info.st_nlink != 2:
            raise InstallError(
                f"possible provider staging entry {alias} has link count {active_info.st_nlink}, not exactly 2; left untouched"
            )
        expected_owner = (os.geteuid(), os.getegid())
        if (active_info.st_uid, active_info.st_gid) != expected_owner or (
            alias_info.st_uid,
            alias_info.st_gid,
        ) != expected_owner:
            raise InstallError(f"possible provider staging entry {alias} has an unexpected owner/group; left untouched")
        expected_mode = 0o644
        if stat.S_IMODE(active_info.st_mode) != expected_mode or stat.S_IMODE(alias_info.st_mode) != expected_mode:
            raise InstallError(f"possible provider staging entry {alias} has unexpected permissions; left untouched")

        fd = os.open(
            name,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | NOFOLLOW | getattr(os, "O_NONBLOCK", 0),
            dir_fd=parent_fd,
        )
        try:
            opened = os.fstat(fd)
            if (opened.st_dev, opened.st_ino, opened.st_nlink) != (
                active_info.st_dev,
                active_info.st_ino,
                2,
            ):
                raise InstallError(f"active settings changed while validating staging entry {alias}; left untouched")
            data = read_open_file(fd)
            after_read = os.fstat(fd)
            stable_fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_mode", "st_uid", "st_gid", "st_nlink")
            if any(getattr(opened, key) != getattr(after_read, key) for key in stable_fields):
                raise InstallError(f"active settings changed while validating staging entry {alias}; left untouched")
        finally:
            os.close(fd)
        if data != expected_new_hook_payload(provider):
            raise InstallError(
                f"possible provider staging entry {alias} does not match the installer's expected {provider} settings; left untouched"
            )

        # Recheck the candidate, but never unlink it: a pathname can be replaced
        # after any lstat/identity check, and unlink would then delete user data.
        current_active = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        current_alias = os.stat(alias, dir_fd=parent_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(current_active.st_mode)
            or not stat.S_ISREG(current_alias.st_mode)
            or (current_active.st_dev, current_active.st_ino) != (active_info.st_dev, active_info.st_ino)
            or (current_alias.st_dev, current_alias.st_ino) != (active_info.st_dev, active_info.st_ino)
            or current_active.st_nlink != 2
            or current_alias.st_nlink != 2
            or (current_active.st_uid, current_active.st_gid) != expected_owner
            or (current_alias.st_uid, current_alias.st_gid) != expected_owner
            or stat.S_IMODE(current_active.st_mode) != expected_mode
            or stat.S_IMODE(current_alias.st_mode) != expected_mode
        ):
            raise InstallError(f"provider staging entry {alias} changed during validation; left untouched")
        if not verify_parent(root, root_fd, relative, parent_fd):
            raise InstallError(f"target directory moved during staging inspection for {relative}; left untouched")
        if report:
            print(
                f"PRESERVED possible installer staging link {alias} for {relative}; "
                "its origin cannot be proven from its name or metadata, so it was not removed"
            )
        return True
    finally:
        if parent_fd is not None:
            os.close(parent_fd)
        os.close(root_fd)


def op_merge_hook(root, provider, relative, state_path):
    state = load_state(state_path)
    root_fd = open_root(root)
    parent_fd = None
    temporary = None
    temp_fd = None
    try:
        parent_fd, name = open_parent(root_fd, relative, True, state, state_path)
        if not verify_parent(root, root_fd, relative, parent_fd):
            raise InstallError(f"target directory moved or changed after it was opened; refusing settings write: {relative}")
        original = inspect_existing(parent_fd, name, allow_hardlinks=True)
        config = {}
        if original is not None:
            try:
                config = json.loads(original["data"].decode("utf-8"))
            except Exception as exc:
                raise InstallError(f"cannot safely parse {relative}: {exc}; no settings were changed") from exc
        sessions = validate_config(config, relative)
        entry = hook_entry(provider)
        if hook_is_registered(provider, sessions):
            if original is not None and original["nlink"] > 1:
                if original["nlink"] != 2 or not recover_provider_staging(root, provider, report=False):
                    raise InstallError(
                        f"cannot safely accept multiply-linked {relative}; "
                        "no unique verified provider staging candidate was found"
                    )
            print("HOOK PRESENT")
            return
        if original is not None:
            fail(
                f"cannot safely replace pre-existing {relative}: POSIX has no portable conditional replace for non-cooperative writers; file preserved, merge the hook manually",
                status=11,
            )
        sessions.append(entry)
        payload = (json.dumps(config, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        template = {
            "mode": 0o644,
            "uid": os.geteuid(),
            "gid": os.getegid(),
            "atime_ns": time.time_ns(),
            "mtime_ns": time.time_ns(),
            "xattrs": {},
        }
        if not verify_parent(root, root_fd, relative, parent_fd):
            raise InstallError(f"target directory moved or changed before staging settings: {relative}")
        temporary, temp_fd, expected = new_temp(parent_fd, name, payload, template)
        operation = {"path": relative, "expected": expected}
        state["operations"].append(operation)
        save_state(state_path, state)
        if not verify_parent(root, root_fd, relative, parent_fd):
            raise InstallError(f"target directory moved or changed before publishing settings; staged file was not installed: {relative}")
        try:
            os.link(temporary, name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd, follow_symlinks=False)
        except FileExistsError:
            state["operations"].pop()
            save_state(state_path, state)
            raise InstallError(f"{relative} appeared while its hook was being prepared; it was preserved")
        if not verify_parent(root, root_fd, relative, parent_fd):
            print(f"PRESERVED settings written through a directory moved during publication: {relative}", file=sys.stderr)
            raise InstallError(f"target directory moved during settings publication; rollback will preserve uncertain data: {relative}")
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
                if not verify_parent(root, root_fd, relative, parent_fd):
                    print(f"PRESERVED file; destination directory moved or changed before rollback: {relative}", file=sys.stderr)
                    incomplete = True
                    continue
                current = signature_at(parent_fd, name)
                if current is None:
                    continue
                if not same_identity(current, operation["expected"]):
                    print(f"PRESERVED concurrent change; rollback skipped: {relative}", file=sys.stderr)
                    incomplete = True
                    continue
                # Keep the moved inode under a recovery name: another process may
                # still hold a writable descriptor and change it after this check.
                quarantine = f".{name}.rollback-{os.getpid()}-{secrets.token_hex(5)}"
                rename_noreplace(parent_fd, name, quarantine)
                if not verify_parent(root, root_fd, relative, parent_fd):
                    print(f"PRESERVED recovery file in a directory moved during rollback: {relative} ({quarantine})", file=sys.stderr)
                    incomplete = True
                    continue
                moved = signature_at(parent_fd, quarantine)
                if not same_identity(moved, operation["expected"]):
                    try:
                        os.link(quarantine, name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd, follow_symlinks=False)
                    except OSError:
                        print(f"PRESERVED changed file in recovery path {quarantine}: {relative}", file=sys.stderr)
                    incomplete = True
                    continue
                print(f"PRESERVED rollback recovery file {quarantine}: {relative}", file=sys.stderr)
                incomplete = True
            except FileNotFoundError:
                print(f"PRESERVED missing parent; rollback skipped: {relative}", file=sys.stderr)
                incomplete = True
            except OSError as exc:
                print(f"ERROR: rollback could not safely process {relative}: {exc}", file=sys.stderr)
                incomplete = True
            except InstallError as exc:
                print(f"ERROR: rollback could not safely process {relative}: {exc}", file=sys.stderr)
                incomplete = True
            finally:
                if parent_fd is not None:
                    os.close(parent_fd)
        for relative in reversed(state["created_directories"]):
            # A held parent dirfd pins an inode but cannot prove that the inode
            # remains beneath root at the rmdir syscall boundary. Keep even an
            # empty directory rather than risk deleting one moved outside root.
            print(
                f"PRESERVED created directory during rollback; it was not removed because a directory descriptor cannot prove it remains inside the target: {relative}",
                file=sys.stderr,
            )
            incomplete = True
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
        if command == "lock-exec" and len(argv) >= 4:
            lock_and_exec(argv[1], argv[2:])
        elif command == "verify-lock" and len(argv) == 3:
            verify_target_lock(argv[1], argv[2])
        elif command == "recover-hook-staging" and len(argv) == 3:
            recover_provider_staging(argv[1], argv[2])
        elif command == "validate-hook-staging" and len(argv) == 3:
            if not recover_provider_staging(argv[1], argv[2], report=False):
                raise InstallError(f"no verified provider staging candidate exists for {HOOK_SETTINGS.get(argv[2], argv[2])}")
        elif command == "init" and len(argv) == 3:
            root_fd = open_root(argv[1])
            os.close(root_fd)
            save_state(argv[2], {"operations": [], "created_directories": []})
        elif command == "snapshot" and len(argv) == 4:
            snapshot_command(argv[1], argv[2], argv[3])
        elif command == "compare" and len(argv) == 4:
            return compare_command(argv[1], argv[2], argv[3])
        elif command == "copy" and len(argv) == 5:
            op_copy(argv[1], argv[2], argv[3], argv[4])
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
