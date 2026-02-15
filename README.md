<p align="left">
  <img src="custom_components/myhome/frontend/bticino-logo.svg" alt="bticino logo" width="180" />
</p>

# bticino MyHome Unofficial Integration

Custom Home Assistant integration for BTicino/Legrand MyHome gateways over OpenWebNet.

## Project Status

This repository maintains and evolves a fork of the original MyHome integration, with focus on:

- gateway worker stability
- active discovery and passive discovery from bus activity
- web UI for device discovery and configuration
- stronger climate and power support

## Main Features

- gateway setup through Home Assistant Config Flow
- supported platforms: `light`, `cover`, `climate`, `sensor`, `switch`, `binary_sensor`
- custom MyHome services (`sync_time`, `send_message`, discovery services)
- device configuration from web UI (no mandatory `myhome.yml` dependency)
- direct import of discovered devices into runtime configuration
- manual add/remove of devices from the UI
- power endpoint discovery support (`WHO 18`)
- OWNd library vendored inside the integration (`0.7.49`, author: `anotherjulien`)

## Requirements

- Home Assistant (Core or Container)
- IP connectivity from Home Assistant to your MyHome gateway

## Installation

### HACS (recommended)

Prerequisite: HACS must already be installed.

1. Open Home Assistant and go to `HACS`.
2. Open the top-right menu (`⋮`) and choose `Custom repositories`.
3. Add:
   - Repository: `https://github.com/xmavgithub/bticino-myhome-hacs-integration`
   - Category: `Integration`
4. Click `Add`.
5. Search for `bticino MyHome` in HACS and open the integration page.
6. Click `Download` and complete installation.
7. Restart Home Assistant.
8. Go to `Settings` -> `Devices & Services` -> `Add Integration`.
9. Search for `bticino MyHome` and complete the config flow.

Optional direct link:

`https://my.home-assistant.io/redirect/hacs_repository/?owner=xmavgithub&repository=bticino-myhome-hacs-integration&category=integration`

### Manual

1. Copy `custom_components/myhome` to `config/custom_components/myhome`.
2. Restart Home Assistant.
3. Add and configure `bticino MyHome` from `Settings` -> `Devices & Services`.

## Device Configuration

Use the integration web panel to manage devices:

- automatic discovery by activation (passive collection)
- import discovered devices into configuration
- manual device creation and deletion

## Legacy YAML Migration

If a legacy YAML file (for example `myhome.yml`) is present, it can be used for one-time migration into integration storage.

Example legacy file:

- `examples/myhome.yml`

## Troubleshooting

- If entities stop updating after changes, restart Home Assistant.
- If discovery fails, inspect logs for `custom_components.myhome`.
- Verify gateway reachability, IP address, and credentials.

## Fork Credits

This project started as a fork of the original integration:

- https://github.com/anotherjulien/MyHOME

Thanks to the original maintainers and contributors.

## License

See `LICENSE`.
