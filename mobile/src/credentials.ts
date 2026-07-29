import * as SecureStore from 'expo-secure-store';

import type { Credentials } from './types';

const CREDENTIALS_KEY = 'arfoxia.credentials.v1';

const secureOptions: SecureStore.SecureStoreOptions = {
  keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
  requireAuthentication: false,
};

export async function loadCredentials(): Promise<Credentials | null> {
  const encoded = await SecureStore.getItemAsync(CREDENTIALS_KEY, secureOptions);
  if (!encoded) {
    return null;
  }
  try {
    const value = JSON.parse(encoded) as Partial<Credentials>;
    if (
      value.version !== 1 ||
      typeof value.baseUrl !== 'string' ||
      typeof value.token !== 'string'
    ) {
      return null;
    }
    return value as Credentials;
  } catch {
    return null;
  }
}

export async function saveCredentials(credentials: Credentials): Promise<void> {
  await SecureStore.setItemAsync(
    CREDENTIALS_KEY,
    JSON.stringify(credentials),
    secureOptions,
  );
}

export async function clearCredentials(): Promise<void> {
  await SecureStore.deleteItemAsync(CREDENTIALS_KEY, secureOptions);
}
