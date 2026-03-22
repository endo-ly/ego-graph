import type { ExtensionSettings, SyncStatus } from "../shared/types.js";

const SETTINGS_KEY = "settings";
const STATUS_KEY = "sync_status";
let syncStatusLock: Promise<void> = Promise.resolve();

function getStorageArea(storageArea: chrome.storage.StorageArea = chrome.storage.local) {
  return storageArea;
}

export async function getSettings(
  storageArea: chrome.storage.StorageArea = chrome.storage.local
): Promise<Partial<ExtensionSettings>> {
  const result = await getStorageArea(storageArea).get(SETTINGS_KEY);
  return (result[SETTINGS_KEY] as Partial<ExtensionSettings> | undefined) ?? {};
}

export async function saveSettings(
  settings: ExtensionSettings,
  storageArea: chrome.storage.StorageArea = chrome.storage.local
): Promise<void> {
  await getStorageArea(storageArea).set({ [SETTINGS_KEY]: settings });
}

export async function getSyncStatus(
  storageArea: chrome.storage.StorageArea = chrome.storage.local
): Promise<SyncStatus> {
  const result = await getStorageArea(storageArea).get(STATUS_KEY);
  return (result[STATUS_KEY] as SyncStatus | undefined) ?? {};
}

export async function saveSyncStatus(
  status: SyncStatus,
  storageArea: chrome.storage.StorageArea = chrome.storage.local
): Promise<void> {
  await getStorageArea(storageArea).set({ [STATUS_KEY]: status });
}

export async function getLastSuccessfulSyncAt(
  storageArea: chrome.storage.StorageArea = chrome.storage.local
): Promise<string | undefined> {
  const status = await getSyncStatus(storageArea);
  return status.lastSuccessfulSyncAt;
}

export async function setSuccessfulSync(
  timestamp: string,
  storageArea: chrome.storage.StorageArea = chrome.storage.local
): Promise<void> {
  syncStatusLock = syncStatusLock.then(async () => {
    const current = await getSyncStatus(storageArea);
    await saveSyncStatus(
      {
        ...current,
        lastAttemptedSyncAt: new Date().toISOString(),
        lastSuccessfulSyncAt: timestamp,
        lastResult: "success",
        lastErrorMessage: undefined
      },
      storageArea
    );
  });
  return syncStatusLock;
}

export async function setFailedSync(
  message: string,
  storageArea: chrome.storage.StorageArea = chrome.storage.local
): Promise<void> {
  syncStatusLock = syncStatusLock.then(async () => {
    const current = await getSyncStatus(storageArea);
    await saveSyncStatus(
      {
        ...current,
        lastAttemptedSyncAt: new Date().toISOString(),
        lastResult: "error",
        lastErrorMessage: message
      },
      storageArea
    );
  });
  return syncStatusLock;
}
