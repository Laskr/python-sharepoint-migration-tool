# README.md

## SharePoint Cross-Site Migration Utility

This is an enterprise-grade Python utility for performing a large-scale, targeted migration of folders and their contents between two separate SharePoint Online sites.

### The Problem

This tool was developed to solve a real-world business need: migrating over 1,600 client folders based on specific naming conventions. Standard low-code tools like Power Automate proved insufficient, failing due to hard limits on data size (200MB metadata limit), API throttling, and a lack of robust error handling and auditing for such a large operation.

### The Solution

This application interacts directly with the Microsoft Graph API using `asyncio` for high-performance, concurrent operations. It is designed to be resilient, configurable, and provides a full audit trail to ensure 100% data fidelity.

### Features

- **High Performance:** Built with `asyncio` and `aiohttp` to initiate and monitor multiple copy jobs concurrently.
- **Configurable & Scalable:** All site IDs, paths, keywords, and performance parameters (concurrency, batching, retries) are managed in external configuration files, not hard-coded.
- **Robust Error Handling:** Automatically retries transient API errors with exponential backoff and intelligently handles API rate-limiting (HTTP 429) by respecting server `Retry-After` headers.
- **True Completion Monitoring:** Initiates asynchronous server-side copy jobs and then polls the monitoring endpoints provided by the Graph API to ensure each job is tracked to its final `completed` or `failed` state.
- **Comprehensive Auditing:** Performs a post-migration audit by generating manifests of source and destination folders and comparing item counts, providing a detailed success/failure report.

### Prerequisites

1. **Python 3.9+**
2. **An Azure Entra ID (formerly Azure AD) Application Registration** with the following **Application** API permissions granted for Microsoft Graph:
    - `Sites.ReadWrite.All` (or `Sites.FullControl.All`)
    - Admin consent must be granted for these permissions.

### Setup

1. **Clone the repository:**

    ```bash
    git clone https://github.com/your-username/sharepoint-folder-migration.git
    cd sharepoint-folder-migration
    ```

2. **Create and activate a Python virtual environment:**

    ```bash
    # Windows
    python -m venv .venv
    .\.venv\Scripts\activate

    # macOS/Linux
    python3 -m venv .venv
    source .venv/bin/activate
    ```

3. **Install dependencies:**

    ```bash
    pip install -r requirements.txt
    ```

4. **Configure:**
    - Rename `.env.example` to `.env` and fill in your secret credentials (Tenant ID, Client ID, Client Secret, Site IDs, Drive IDs).
    - Edit `config/config.yaml` to define the source/destination paths and the keywords for filtering.

### Usage

Once configured, run the migration from the project's root directory:

```bash
python main.py
```

The script will log its progress to the console. A detailed, human-readable summary and audit report will be saved to a timestamped file in the `logs/` directory upon completion.

### Project Structure

.
├── .env.example          # --- Template for environment variables
├── requirements.txt      # --- Project dependencies
├── config/
│   └── config.yaml       # --- Non-secret configuration (paths, keywords, performance)
├── clients/
│   └── sharepoint_client.py # --- Handles all Graph API communication and resilience
├── main.py               # --- Main entry point and orchestrator
└── utils/
    ├── completion_logger.py # --- Generates the final summary/audit log
    └── logging_setup.py     # --- Sets up application-wide logging

## Troubleshooting

| Error / Symptom                                  | Probable Cause & Solution |
| `Could not find the source/destination folder. Exiting.` | 1. The `DRIVE_ID` or `SITE_ID` in your `.env` is incorrect. Re-verify it using Graph Explorer. 2. The folder path in `config.yaml` has a typo. 3. The folder genuinely does not exist on that specific site/drive. |
| Authentication errors (401/403)                         | 1. The `CLIENT_SECRET` in your `.env` may have expired. Generate a new one in Entra ID. 2. The Entra App Registration is missing the required `Sites.ReadWrite.All` API permission, or admin consent has not been granted.                                    |
| All copy jobs fail with `conflictBehavior` errors      | If you have set `CONFLICT_BEHAVIOR` to `fail` in your `.env`, this is expected behavior if the destination folders already exist. Change to `rename` or `replace` for subsequent runs.                                                                          |

## Disclaimer

This is a powerful utility designed for a specific, one-time migration task. It directly interacts with the Microsoft Graph API with high-level permissions (`Sites.ReadWrite.All`).

- **Test First:** Always run the script against a test source and destination before executing it on live production data.
- **Use with Care:** Verify your `.env` and `config.yaml` configuration carefully to ensure you are modifying the correct SharePoint environments.
- **Intended Use:** This script is designed to copy top-level folders. It is not designed for continuous synchronization.
