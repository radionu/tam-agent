# Installing a reviewed Linux client

Ask the TAM coordinator for the exact approved bootstrap script, independent script and platform descriptor SHA-256 pins, signed runtime assets, provisioned publisher public keys and installation instructions. Keep your device invitation private.

Verify the independently supplied script pin before any root execution. The bootstrap downloader fetches and verifies files into a protected staging directory; it does not enroll the device, start a service or change publisher trust. Follow the coordinator's explicit admin staging and activation procedure afterward.

Never install a fixture release, bypass a signature failure, replace a published file or retrieve trust automatically from the same download location. Report failed checks to the coordinator before retrying.
