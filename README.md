# Mapping Party Tracker

A real-time collaborative web application for claiming, scoring, and releasing map polygons during mapping events and data validation sessions.

Vibe-coded with Claude. See the generated description and installation instructions in [Claude-Readme](Claude-Readme.md).

## Prompts

The prompt was built with ChatGPT. The original prompt:

> Hey ChatGPT. I need you to write a prompt for Claude Code to produce a web app for tracking polygon ownership. I heard you do it better than a human. Please be precise and adhere to best practices for prompting.

> I want a website with a JavaScript/JQuery-based frontend (nothing complex, no node/bun, no packaging and pre-processing whatsoever) and a Python/FastAPI backend.

> People would come to the website and see a list of projects and a login button. Users login via OpenStreetMap OAuth2. After logging in, there is an "add project" button. When clicking it, one can upload a GeoJSON of polygons.

> Polygons are stored in a MySQL database, one feature per row plain text, with indices by project (and unique numeric primary keys of course, generated automatically). Also those rows have a field for a status (an integer number between 0 and 5). Another table links polygons and users: users can "claim" a polygon, which results in a row with both ids, a claim date, and an empty release data. They can later "release" a polygon, filling in the release column in that row. After than, another user can claim the same polygon.

> That's what happens when a user chooses a project on the main screen: they see a map with all the polygons for the given project colored by their status field: 0 empty, 1 red, 3 yellow, 5 green (50% opacity). The outline indicates whether the polygon is claimed: thin black for unclaimed, thick blue for claimed, thick red for the one claimed by the user. There is a floating side bar at the top right corner showing statistics: how many polygons, how many claimed, a small histogram for quantities per score. And a button for the project owner to edit the project (locking/unlocking participation, or updating polygons from another GeoJSON, keeping polygon ids and info that are the same, and warning if we're changing some polygons that have non-zero status). The sidebar also should have a owner-modifiable title, and a owner-editable link with customizable text.

> When clicking a polygon, a popup appears. If it's been claimed by another user, the message contains their name. If not, and a user does not have claimed polygons, then a "Claim" button. After tapping, if the user is not logged in, first it should navigate to OSM OAuth2, and then back and claim the piece. Or just claim it firsthand. If the polygon is already claimed by user, then a row of scores, and a "Release" button underneath them. Clicking a score changes it in the database, but does not close the popup. Clicking "Release" releases the polygon and closes the popup. When a user has a claimed polygon, then popups on other unclaimed polygons should indicate that they have to release that polygon first.

> All changed in scores and claimed statuses should be updated live after any changes in the database. I'm not sure which technology to use here, probably something related to sockets idk.

> The backend should be written with just the required libraries: mysql-connector for database access, fastapi for api, authlib for oauth2 (make it secure with osm/oauth2 authentication and some secure tokens). It should have a pyproject.toml and be runnable locally with uv run. The frontend is just a set of static files: single css file, htmls for initial project list, the map, and a project editing pages, and js where needed. It should look fine on a phone, but the desktop is primary.

> Please make a prompt to claude code, not the resulting code.

I then needed to clarify a couple things:

> Please give the Claude-optimized version indeed. Also mention the project editing page as a separate page, not as a part of the sidebar. Use orange for status 2 and light-green for status 4. Do not mention the project structure -- I assume Claude Code can devise it themselves. Mention how the secrets (db credentials, secret keys etc) should be stored. The project name is "Mapping Party Tracker".

After that, I copy-pasted the result into Claude, and made it fix a couple issues I encountered.

Given I have asked it to use tech as simple as possible, I can review and merge pull requests. I understand if you don't want to look inside. Also I'd be grateful for security issues you find, since I'm not proficient with web sockets and secure API calls.

## OSM to GeoJSON

I have written (by hand) a script to simplify creating polygons using JOSM. 

See the [tool](tool/) directory.

## License and Author

Prompts were authored by Ilya Zverev, code is published under the ISC license.
