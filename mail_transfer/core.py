from concurrent.futures import ThreadPoolExecutor, as_completed

from imap_tools import MailBox, FolderInfo
from imap_tools.errors import MailboxFolderCreateError

from mail_transfer.progress import NULL_REPORTER, ProgressReporter

ABSOLUTE_MAX_THREADS = 20

SKIP_FOLDER_FLAGS = {"\\Drafts", "\\Sent", "\\Trash", "\\Junk"}
SKIP_FOLDER_NAMES = {
    "drafts",
    "sent", "sent items", "sent messages",
    "trash", "deleted items", "deleted messages",
    "junk", "junk e-mail", "spam",
}


def folder_leaf_name(folder: FolderInfo) -> str:
    delim = folder.delim or "/"
    return folder.name.rsplit(delim, 1)[-1].strip().lower()


def is_skipped_system_folder(folder: FolderInfo) -> bool:
    if any(flag in folder.flags for flag in SKIP_FOLDER_FLAGS):
        return True
    return folder_leaf_name(folder) in SKIP_FOLDER_NAMES


class EmailInfo:
    def __init__(self, imap_host, email, password):
        self.imap_host = imap_host
        self.email = email
        self.password = password


def copy_message(message, folder: str, dest: MailBox):
    dest.append(message, folder, dt=message.date, flag_set=message.flags)


def build_dest_folder(src_info: EmailInfo, folder: FolderInfo) -> str:
    parts = folder.name.split(folder.delim) if folder.delim else [folder.name]
    parts = [p for p in parts if p]
    return "/".join([src_info.email, *parts])


def ensure_dest_folder(dest: MailBox, dest_folder: str):
    try:
        dest.folder.create(dest_folder)
    except MailboxFolderCreateError as e:
        if b"ALREADYEXISTS" not in e.command_result[1][0]:
            raise


def copy_folder(source: MailBox, src_info: EmailInfo, folder: FolderInfo, dest: MailBox,
                 reporter: ProgressReporter = NULL_REPORTER):
    source.folder.set(folder.name)

    dest_folder = build_dest_folder(src_info, folder)
    ensure_dest_folder(dest, dest_folder)

    total = source.folder.status(folder.name, ["MESSAGES"])["MESSAGES"]
    reporter.start_folder(folder.name, total)

    done = 0
    for m in source.fetch(bulk=100, mark_seen=False):
        copy_message(m, dest_folder, dest)
        done += 1
        reporter.advance_message(folder.name, done, total)

    reporter.finish_folder(folder.name)


def copy_folder_worker(src_info: EmailInfo, dst_info: EmailInfo, folder: FolderInfo,
                        reporter: ProgressReporter = NULL_REPORTER):
    try:
        with MailBox(src_info.imap_host).login(src_info.email, src_info.password) as source, \
             MailBox(dst_info.imap_host).login(dst_info.email, dst_info.password) as dest:
            copy_folder(source, src_info, folder, dest, reporter=reporter)
    except Exception as e:
        reporter.error(folder.name, str(e))
        raise


def copy_all_folders(source: MailBox, src_info: EmailInfo, dst_info: EmailInfo, dest: MailBox,
                      copy_inbox: str, threads: int, reporter: ProgressReporter = NULL_REPORTER):
    threads = max(1, min(threads, ABSOLUTE_MAX_THREADS))

    # Create folder where all copied folders will be put
    if not dest.folder.exists(src_info.email):
        dest.folder.create(src_info.email)

    folders = [f for f in source.folder.list() if "\\Noselect" not in f.flags]
    folders_to_copy = []
    for f in folders:
        if is_skipped_system_folder(f):
            continue
        if (copy_inbox == "n" and (f.name == "INBOX" or "\\All" in f.flags)):
            continue
        folders_to_copy.append(f)

    reporter.start_job(len(folders_to_copy), [f.name for f in folders_to_copy])

    with ThreadPoolExecutor(max_workers=threads) as executor:
        futures = [
            executor.submit(copy_folder_worker, src_info, dst_info, f, reporter)
            for f in folders_to_copy
        ]
        for future in as_completed(futures):
            future.result()

    reporter.finish_job()
