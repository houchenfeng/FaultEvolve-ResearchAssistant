import type { CapacitorConfig } from '@capacitor/cli';

const config: CapacitorConfig = {
  appId: 'com.faultevolve.edgetwin',
  appName: 'FaultEvolve 机房孪生',
  webDir: 'dist',
  server: {
    // Plain-http origin so the page may open ws:// to the laptop on the LAN.
    androidScheme: 'http',
    cleartext: true,
  },
  android: {
    allowMixedContent: true,
    backgroundColor: '#05080f',
  },
};

export default config;
