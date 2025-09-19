import asyncio
import os
from typing import Dict, List

import yaml
from dotenv import load_dotenv

from clients.sharepoint_client import SharePointClient
from utils.completion_logger import CompletionStatusLogger
from utils.logging_setup import logger, setup_logging

# ==============================================================================
# --- Configuration Loading ---
# ==============================================================================
setup_logging()
load_dotenv()

# --- Site IDs from .env ---
SOURCE_SITE_ID = os.getenv("SOURCE_SITE_ID")
SOURCE_DRIVE_ID = os.getenv("SOURCE_DRIVE_ID")
DESTINATION_SITE_ID = os.getenv("DESTINATION_SITE_ID")
DESTINATION_DRIVE_ID = os.getenv("DESTINATION_DRIVE_ID")

# --- Application Config from YAML ---
try:
    with open("config/config.yaml", "r") as f:
        config = yaml.safe_load(f)
    PATHS = config.get("paths", {})
    MIGRATION_CONFIG = config.get("migration", {})
    PERFORMANCE_CONFIG = config.get("performance", {})

    SOURCE_ROOT_FOLDER_PATH = PATHS.get("source_root")
    DESTINATION_ROOT_FOLDER_PATH = PATHS.get("destination_root")
    CONFLICT_BEHAVIOR = MIGRATION_CONFIG.get("conflict_behavior", "rename")
    KEYWORDS = MIGRATION_CONFIG.get("migration_keywords", [])

    # Get performance settings from YAML
    MAX_CONNECTIONS = PERFORMANCE_CONFIG.get("max_connections", 10)
    MAX_RETRIES = PERFORMANCE_CONFIG.get("max_retries", 5)
    RETRY_DELAY = PERFORMANCE_CONFIG.get("retry_delay_seconds", 2)
    BATCH_SIZE = PERFORMANCE_CONFIG.get("batch_size", 50)
    POST_PROCESSING_WAIT_TIME = PERFORMANCE_CONFIG.get(
        "post_processing_wait_time", 60
    )  # in seconds

except FileNotFoundError:
    logger.error("FATAL: config/config.yaml not found.")
    exit(1)
except Exception as e:
    logger.error(f"FATAL: Error parsing config.yaml: {e}", exc_info=True)
    exit(1)


# ==============================================================================
# --- Core Logic ---
# ==============================================================================
async def get_all_top_level_folders(
    client: SharePointClient, folder_id: str
) -> List[Dict]:
    """
    Fetches ALL top-level folders from a given folder ID, including the 'folder'
    facet which contains the childCount for verification.
    """
    all_folders = []
    # Request the 'folder' facet to get childCount
    endpoint = (
        f"/drives/{client.drive_id}/items/{folder_id}/children"
        "?$filter=folder ne null&$select=id,name,folder"
    )

    while endpoint:
        response, _ = await client.make_request("GET", endpoint)
        if not response or "value" not in response:
            logger.error(f"Failed to retrieve folder list from endpoint: {endpoint}")
            break
        all_folders.extend(response.get("value", []))
        endpoint = (
            response.get("@odata.nextLink", "").replace(
                "https://graph.microsoft.com/v1.0", ""
            )
            if "@odata.nextLink" in response
            else None
        )

    return all_folders


async def copy_folder(
    source_client: SharePointClient, folder: Dict, dest_parent_id: str
) -> bool:
    """
    Initiates the copy of a single folder. This is a "fire-and-forget" operation.
    """
    folder_name = folder.get("name", "Unknown")

    endpoint = f"/drives/{source_client.drive_id}/items/{folder['id']}/copy"
    payload = {
        "parentReference": {"driveId": DESTINATION_DRIVE_ID, "id": dest_parent_id},
        "name": folder_name,
        "@microsoft.graph.conflictBehavior": CONFLICT_BEHAVIOR,
    }

    response_body, _ = await source_client.make_request("POST", endpoint, json=payload)

    # A successful initiation returns a non-None response body
    if response_body is not None:
        logger.info(f"Copy job for '{folder_name}' successfully initiated.")
        return True
    else:
        logger.error(f"Failed to initiate copy job for '{folder_name}'.")
        return False


async def main():
    """Main function to orchestrate the folder filtering and copying process."""
    completion_logger = CompletionStatusLogger()

    # Validate all necessary IDs are loaded
    required_ids = {
        "SOURCE_SITE_ID": SOURCE_SITE_ID,
        "SOURCE_DRIVE_ID": SOURCE_DRIVE_ID,
        "DESTINATION_SITE_ID": DESTINATION_SITE_ID,
        "DESTINATION_DRIVE_ID": DESTINATION_DRIVE_ID,
    }
    if not all(required_ids.values()):
        missing = [k for k, v in required_ids.items() if not v]
        logger.error(f"Missing critical ID variables in .env file: {missing}. Exiting.")
        return

    if not KEYWORDS:
        logger.error(
            "FATAL: The 'migration_keywords' list in config.yaml is empty. Exiting."
        )
        return

    client_args = {
        "max_connections": MAX_CONNECTIONS,
        "max_retries": MAX_RETRIES,
        "retry_delay": RETRY_DELAY,
    }

    source_client = None
    dest_client = None
    try:
        source_client = SharePointClient(
            site_id=SOURCE_SITE_ID, drive_id=SOURCE_DRIVE_ID, **client_args
        )
        await source_client.__aenter__()

        dest_client = SharePointClient(
            site_id=DESTINATION_SITE_ID,
            drive_id=DESTINATION_DRIVE_ID,
            **client_args,
        )
        await dest_client.__aenter__()

        # --- 1. Find Root Folders ---
        logger.info(f"Locating source folder: '{SOURCE_ROOT_FOLDER_PATH}'")
        source_root = await source_client.find_folder_by_path(SOURCE_ROOT_FOLDER_PATH)
        if not source_root:
            return

        logger.info(f"Locating destination folder: '{DESTINATION_ROOT_FOLDER_PATH}'")
        dest_root = await dest_client.find_folder_by_path(DESTINATION_ROOT_FOLDER_PATH)
        if not dest_root:
            return

        # --- 2. Identify, Filter, and Log Folders to Migrate ---
        logger.info("Identifying and filtering source folders...")
        all_source_folders = await get_all_top_level_folders(
            source_client, source_root["id"]
        )

        folders_to_copy = [
            folder
            for folder in all_source_folders
            if any(keyword in folder.get("name", "").lower() for keyword in KEYWORDS)
        ]

        if not folders_to_copy:
            logger.warning("No folders found matching the specified keywords.")
            return

        completion_logger.log_folders_found(folders_to_copy)

        # --- 3. Execute Copy and Wait for Completion ---
        all_tasks = []
        for i in range(0, len(folders_to_copy), BATCH_SIZE):
            batch = folders_to_copy[i : i + BATCH_SIZE]
            total_batches = -(-len(folders_to_copy) // BATCH_SIZE)
            logger.info(
                f"--- Preparing Batch {i // BATCH_SIZE + 1}/{total_batches} ({len(batch)} folders) ---"
            )
            all_tasks.extend(
                [
                    copy_folder(source_client, folder, dest_root["id"])
                    for folder in batch
                ]
            )

        logger.info(f"Initiating copy for all {len(all_tasks)} folders...")
        results = await asyncio.gather(*all_tasks)

        for folder, result in zip(folders_to_copy, results):
            completion_logger.log_copy_initiation(folder, result)

        # --- 4. Post-Migration Audit ---
        logger.info(
            f"--- All copy jobs initiated. Waiting {POST_PROCESSING_WAIT_TIME} seconds for server-side processing before starting audit. ---"
        )
        await asyncio.sleep(
            POST_PROCESSING_WAIT_TIME
        )  # Wait time after copy jobs finished initiating to allow processing to complete

        logger.info("Starting post-migration audit of destination folder...")
        all_dest_folders = await get_all_top_level_folders(dest_client, dest_root["id"])
        completion_logger.log_destination_folders(all_dest_folders)

    finally:
        # --- 5. Log Final Summary and Audit Results ---
        # This block runs regardless of success or failure in the 'try' block.
        if completion_logger:
            completion_logger.perform_final_audit_and_log_summary()

        # --- 6. Cleanup ---
        if source_client:
            await source_client.close()
        if dest_client:
            await dest_client.close()
        logger.info("Script finished.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.warning("Script execution cancelled by user (Ctrl+C).")
