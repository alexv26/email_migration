class ProgressReporter:
    """Null-object base class. Subclass and override only what you need."""

    def start_job(self, total_folders: int, folder_names: list) -> None:
        pass

    def start_folder(self, folder_name: str, total_messages: int) -> None:
        pass

    def advance_message(self, folder_name: str, done: int, total: int) -> None:
        pass

    def finish_folder(self, folder_name: str) -> None:
        pass

    def finish_job(self) -> None:
        pass

    def error(self, folder_name, message: str) -> None:
        pass


NULL_REPORTER = ProgressReporter()
