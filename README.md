# Collaboratorium
An environment for collaborative innovation

## Feedback Process

We are excited to hear feedback on this tool!

Please submit reports on how you use this tool and how it's helped you identify connections and understand your collaboration network by going to 
> Issues (in the top left) -> New Issue (top right) -> Use Report

Likewise, you will find templates for bug reports and feature requests.

## Development
For local testing, run `python ./collaboratorium/main.py`

## Hosting
For running in Docker, use the standard `docker compose build` then `docker compose up`

For Auth, register the app in Google Cloud Console and set the redirect URI to `{site_url}/auth/callback`

## Setting up a config.yaml from DBML schema
The config gen script can produce a rough config, but work needs to be done to better handle links, I needed to manually add the links for non-link-tables. Some customization to types and appearance eg. using email fields instead of strings can be done in the forms confi