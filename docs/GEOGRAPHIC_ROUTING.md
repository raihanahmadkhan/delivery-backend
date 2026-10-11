# Geographic routing in RouteLab

The primary workspace is a real map; the research tools remain underneath it. No API keys, paid plans, or commercial routing APIs are needed. The current app uses a shared workspace without sign-in.

## Plan a route

1. **Places:** type a city, landmark, or address. Suggestions appear after a short pause and favor the current map area. Click a suggestion or select it with the arrow keys and Enter, then use it as the depot or a delivery. Alternatively choose Set depot/Add deliveries and click the map. The keyboard-accessible map-center action also selects a location. Drag unfrozen markers to refine them.
2. **Fleet:** choose the available vehicles and their shared capacity. Demand is measured in your own consistent units, not implicitly kilograms.
3. **Constraints:** set the shift, optional maximum distance, and each stop's demand, service time, and service-start window. Times are minutes from midnight (480 = 08:00). Routes must return to the depot within both the depot window and shift.
4. **Solve:** select the method and budget, then Build roads & solve. RouteLab obtains and freezes the road matrix before starting the durable optimization job. All customers must be served; feasible solutions minimize vehicles first, distance second.

Completed results show road geometry where it can be verified, linked vehicle colors, independent schedules, and the retained input/provenance. Editing a draft never changes a saved result. **Edit locations & rebuild roads** deliberately detaches a frozen matrix. Existing browser drafts survive the update; **New route** starts a fresh geographic draft.

**Saved scenarios & benchmarks** contains synthetic examples, saved snapshots, imports, and JSON editing. These use exactly the same matrix/solver/validator contracts. Experiments freeze one road matrix before all seed/method trials. They do not call a routing service for each candidate or trial.

## What road estimates mean

- OSRM supplies directed distances and travel times, including asymmetric road access. Metres become kilometres; seconds become minutes. Unreachable arcs remain `null`.
- Distances are along the routing profile's **fastest paths**, not necessarily shortest-distance paths. Estimates use the road graph and driving profile, not live traffic, delivery access guarantees, truck restrictions, or current closures.
- Each selected point must snap to a drivable road within 200 metres. The visible marker is the requested delivery position; travel begins/ends at its stored road snap. Off-road access/walking/loading is not modeled as driving. Service time is separate.
- Road-mode inputs without a matrix are rejected by the optimizer. Road failures and fallback-speed responses never silently become Haversine travel.
- Snapshot metadata records coordinate identity, provider identity, data version, capture time, snapped locations, and OSRM hints. The matrix is embedded in run artifacts. Changing locations invalidates the snapshot; changing constraints does not.
- Final geometry is requested with the saved snap hints and checked against every directed matrix leg (10 m / 1 s tolerance). If the provider's graph changed or a leg disagrees, the UI reports unavailable geometry and preserves saved metrics. It does not draw invented road lines.
- Search replay intentionally shows dashed **stop order**, not a road route. Arbitrary imported matrices without road provenance show locations only.

The public service does not publish an immutable extract version, so provenance honestly records `community-unversioned`. Acquisition is cached in daily buckets; existing saved matrices remain fixed across days. Self-hosting with a declared extract/profile version is the reproducible road-data option.

## Defaults, privacy, and limits

| Component | Default | Self-host configuration |
| --- | --- | --- |
| Map tiles | OpenStreetMap standard raster tiles | `ROUTELAB_TILE_URL` browser-reachable XYZ template |
| Place suggestions | Photon community server | `ROUTELAB_PHOTON_URL` |
| Road matrix/geometry | OSRM community server | `ROUTELAB_OSRM_URL` plus `ROUTELAB_OSRM_DATA_VERSION` |

The browser requests visible tiles. After at least two characters and a 500 ms typing pause, search text is sent through the backend to Photon with the map center rounded to two decimal places for relevance. Selected coordinates go to OSRM when building roads or requesting final geometry. No user geolocation permission or background location collection is used. Do not send sensitive addresses to community providers; configure local services first if privacy requires it.

Community providers are for light interactive use, not a production SLA or bulk/shared service. RouteLab caps public road requests at **25 deliveries**; a self-hosted engine supports **100**. Frozen inputs can still be optimized without a provider connection. The backend schedules requests at least 1.1 seconds apart per service across processes sharing the SQLite notebook, caps queue waiting, and caches search, matrices, and geometry. Separate installations/databases do not coordinate these limits. No tile downloading, prefetching, or offline tile scraping is implemented.

Provider policy/reference links: [OSM tile policy](https://operations.osmfoundation.org/policies/tiles/), [Photon project and community usage](https://github.com/komoot/photon), [OSRM demo policy](https://github.com/Project-OSRM/osrm-backend/wiki/Demo-server), [OSRM API](https://project-osrm.org/docs/v5.24.0/api/).

## Self-host the road engine

Use a compatible free/open-source OCI engine with Compose, or build OSRM natively. This optional setup consumes local RAM/disk and needs an initial regional OSM extract download. Use a suitably small region first. OSRM and map datasets are not silently downloaded by the application.

The included override uses OSRM **v26.9.0** and contraction hierarchies (CH), which support the required table distance annotations. Prepare the dataset using the **same image version** that serves it. The upstream [OSRM instructions](https://github.com/Project-OSRM/osrm-backend) describe preprocessing and resource requirements.

PowerShell, from the workspace root:

```powershell
New-Item -ItemType Directory -Path road-data -Force
$env:ROUTELAB_OSRM_DATA_DIR = (Resolve-Path road-data).Path
$env:ROUTELAB_OSRM_IMAGE = 'ghcr.io/project-osrm/osrm-backend:v26.9.0-debian'
```

Download an appropriately licensed regional `.osm.pbf` extract (for example from [Geofabrik](https://download.geofabrik.de/)) into that directory as **region.osm.pbf**. Preserve its date/license and OSM attribution. Then:

```powershell
docker run --rm -v "${env:ROUTELAB_OSRM_DATA_DIR}:/data" $env:ROUTELAB_OSRM_IMAGE osrm-extract -p /opt/car.lua /data/region.osm.pbf
docker run --rm -v "${env:ROUTELAB_OSRM_DATA_DIR}:/data" $env:ROUTELAB_OSRM_IMAGE osrm-contract /data/region.osrm
# Replace this example with the actual extract date and profile/build identity.
$env:ROUTELAB_OSRM_DATA_VERSION = 'my-region-2026-09-23-car-v26.9.0'
docker compose -f docker-compose.yml -f docker-compose.roads.yml config --quiet
docker compose -f docker-compose.yml -f docker-compose.roads.yml up --build -d
```

Open http://localhost:8080. The API reaches `http://osrm:5000`; the engine's diagnostic port binds only to localhost. Prepared road files are mounted read-only. The road service can take time to load its graph; a request during startup returns an explicit retryable error rather than synthetic travel. Update the data-version string whenever the graph/profile changes. The override intentionally refuses to start without a data path and version.

For a native RouteLab API and separately running local OSRM:

```powershell
$env:ROUTELAB_OSRM_URL = 'http://127.0.0.1:5000'
$env:ROUTELAB_OSRM_DATA_VERSION = 'my-region-2026-09-23-car-v26.9.0'
# Start/restart the API in this terminal after setting these variables.
```

Only the known HTTPS community endpoints or loopback/named local `osrm` and `photon` services are accepted. API callers cannot submit arbitrary backend URLs. No redirects are followed.

## Self-host search and tiles

Follow the [official Photon setup](https://github.com/komoot/photon) to run its open-source Java service with an appropriate regional search database. It is separate from the OSRM road graph; a world search database can require substantial resources. Then set `ROUTELAB_PHOTON_URL=http://127.0.0.1:2322` for a native API, or `http://photon:2322` for a Photon service attached to the Compose network. This project does not bundle a world database or add a large search stack by default.

For tiles, use your own OSM-derived raster XYZ tile service, keeping the required data attribution. The [Switch2OSM serving guide](https://switch2osm.org/serving-tiles/) describes open-source tile-serving options. Set a URL the **browser** can reach, for example:

```powershell
$env:ROUTELAB_TILE_URL = 'http://127.0.0.1:8088/tiles/{z}/{x}/{y}.png'
```

HTTPS is required for remote tile hosts; HTTP is allowed only for loopback. A HTTPS frontend cannot load insecure HTTP tiles. The bundled CSP permits HTTPS tiles and localhost/127.0.0.1 HTTP tiles. Use a loopback hostname rather than a container-only hostname in the tile URL. This configuration supports OSM-derived tiles, whose attribution is displayed by the map; add appropriate attribution in the map component before using datasets with different license requirements.

Set environment variables before starting the API (the native `.env.example` is documentation, not an automatically loaded file). Provider configuration is returned at runtime; the frontend does not need rebuilding. Configure **all three** providers locally for fully self-hosted geographic operation. Benchmarks and optimization on saved matrices remain usable offline without these services, but uncached maps/search/geometry require their providers.

## Validation and troubleshooting

From `backend`, run `python -m unittest discover -s tests -v`; from `frontend`, run `npm run check`. Road-specific tests cover directed unit conversion, no-fallback semantics, matrix identity, geometry consistency, provider boundaries, caching, and request scheduling. Live community checks are intentionally separate from deterministic tests; they must not be hammered by CI.

- **No road near a stop:** move it to an accessible road inside the installed extract. The snap radius is intentionally bounded.
- **Geometry changed:** retain the saved result for comparison; detach/rebuild its working draft for new road data.
- **Service unavailable:** retry later or self-host. No paid key is needed. The API must have outbound access for community defaults.
- **Old UI after updating:** install frontend dependencies with `npm ci`, then restart both servers. Existing drafts are retained; choose New route for the geographic workflow.
- **API works but map tiles fail:** verify the browser-reachable tile URL and HTTPS/CSP rules. Search and optimization do not depend on tile loading.
