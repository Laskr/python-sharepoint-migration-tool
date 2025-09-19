import logging
from datetime import datetime
from typing import Dict, List


class CompletionStatusLogger:
    def __init__(self):
        # Get the logger instance that was already configured by setup_logging()
        self.logger = logging.getLogger("migration_summary")
        self.folders_found: List[Dict] = []
        self.copy_jobs_initiated: List[Dict] = []
        self.failed_copies = 0
        self.folders_in_destination: List[Dict] = []
        self.failed_initiations: List[str] = []

        # Log startup messages
        self.logger.info(
            "===== CLIENT FOLDER MIGRATION PROCESSING COMPLETION STATUS ====="
        )
        self.logger.info(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self.logger.info("=" * 60)

    def log_folders_found(self, folders: List[Dict]):
        """Logs the initial list of folders identified for migration."""
        self.folders_found = folders
        self.logger.info(f"IDENTIFIED {len(folders)} FOLDERS FOR MIGRATION:")
        for folder in folders:
            name = folder.get("name", "Unknown")
            child_count = folder.get("folder", {}).get("childCount", "N/A")
            self.logger.info(f"  - {name} (Contents: {child_count} items)")
        self.logger.info("-" * 60)

    def log_copy_initiation(self, folder: Dict, success: bool):
        """Logs the result of a single copy job initiation."""
        folder_name = folder.get("name", "Unknown")
        if success:
            self.copy_jobs_initiated.append(folder)
            self.logger.info(f"SUCCESS: Copy job initiated for '{folder_name}'")
        else:
            self.failed_initiations.append(folder_name)
            self.logger.error(f"FAILURE: Could not initiate copy for '{folder_name}'")

    def log_destination_folders(self, folders: List[Dict]):
        """Logs the final list of folders found in the destination after migration."""
        self.folders_in_destination = folders

    def perform_final_audit_and_log_summary(self):
        """Performs the final audit and logs the complete summary."""
        self.logger.info("=" * 60)
        self.logger.info("FINAL AUDIT & PROCESSING SUMMARY")
        self.logger.info("-" * 60)

        # --- Convert lists to sets of names for easy comparison ---
        found_names = {f["name"] for f in self.folders_found}
        initiated_names = {f["name"] for f in self.copy_jobs_initiated}
        destination_names = {f["name"] for f in self.folders_in_destination}

        # --- Perform the Audit ---
        self.logger.info("AUDIT 1: Found vs. Initiated")
        if found_names == initiated_names:
            self.logger.info(
                "  [SUCCESS] All identified folders had a copy job successfully initiated."
            )
        else:
            self.logger.error(
                "  [FAILURE] Mismatch between identified folders and initiated jobs."
            )
            missing_initiation = found_names - initiated_names
            if missing_initiation:
                self.logger.error(
                    f"    - Jobs failed to start for: {', '.join(missing_initiation)}"
                )

        self.logger.info("-" * 60)
        self.logger.info("AUDIT 2: Initiated vs. Destination")
        if initiated_names == destination_names:
            self.logger.info(
                "  [SUCCESS] All successfully initiated folders are present in the destination."
            )
        else:
            self.logger.error(
                "  [FAILURE] Mismatch between initiated jobs and final destination contents."
            )
            missing_in_dest = initiated_names - destination_names
            extra_in_dest = destination_names - initiated_names
            if missing_in_dest:
                self.logger.error(
                    f"    - Folders missing from destination: {', '.join(missing_in_dest)}"
                )
            if extra_in_dest:
                self.logger.warning(
                    f"    - Folders found in destination that were not part of this run: {', '.join(extra_in_dest)}"
                )

        self.logger.info("-" * 60)
        self.logger.info("AUDIT 3: Content Count Verification (Child Items)")

        # Create a dictionary for quick lookup of destination folders
        dest_folders_dict = {f["name"]: f for f in self.folders_in_destination}
        mismatch_found = False
        for source_folder in self.folders_found:
            source_name = source_folder.get("name")
            source_count = source_folder.get("folder", {}).get("childCount", -1)

            dest_folder = dest_folders_dict.get(source_name)
            if dest_folder:
                dest_count = dest_folder.get("folder", {}).get("childCount", -2)
                if source_count == dest_count:
                    self.logger.info(
                        f"  [SUCCESS] '{source_name}': Item count matches (Source: {source_count}, Dest: {dest_count})"
                    )
                else:
                    self.logger.error(
                        f"  [FAILURE] '{source_name}': ITEM COUNT MISMATCH (Source: {source_count}, Dest: {dest_count})"
                    )
                    mismatch_found = True
            elif source_name in initiated_names:
                # It should be there but wasn't found
                self.logger.error(
                    f"  [FAILURE] '{source_name}': Was not found in destination for count verification."
                )
                mismatch_found = True

        if not mismatch_found:
            self.logger.info(
                "  [OVERALL SUCCESS] All copied folders have matching item counts."
            )

        # --- Final Stats ---
        self.logger.info("-" * 60)
        self.logger.info(f"Total Folders Identified: {len(self.folders_found)}")
        self.logger.info(
            f"Successful Copy Initiations: {len(self.copy_jobs_initiated)}"
        )
        self.logger.info(f"Failed Copy Initiations: {len(self.failed_initiations)}")
        self.logger.info(
            f"Final Folders in Destination: {len(self.folders_in_destination)}"
        )
        self.logger.info("-" * 60)
        self.logger.info(
            f"Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        self.logger.info("=" * 60)
