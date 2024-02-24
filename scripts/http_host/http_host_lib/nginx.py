import subprocess
import sys
from pathlib import Path

from http_host_lib import DEFAULT_RUNS_DIR, HOST_CONFIG, MNT_DIR, NGINX_DIR, OFM_CONFIG_DIR


def write_nginx_config():
    location_str, curl_text = create_location_blocks()
    curl_text_mix = ''

    if HOST_CONFIG['domain_cf']:
        with open(NGINX_DIR / 'cf.conf') as fp:
            cf_template = fp.read()

        cf_template = cf_template.replace('__LOCATION_BLOCKS__', location_str)
        cf_template = cf_template.replace('__DOMAIN__', HOST_CONFIG['domain_cf'])

        curl_text_mix += curl_text.replace('__DOMAIN__', HOST_CONFIG['domain_cf'])

        with open('/data/nginx/sites/cf.conf', 'w') as fp:
            fp.write(cf_template)
            print('  nginx config written')

    subprocess.run(['nginx', '-t'], check=True)
    subprocess.run(['systemctl', 'reload', 'nginx'], check=True)

    print(curl_text_mix)


def create_location_blocks():
    location_str = ''
    curl_text = ''

    for subdir in MNT_DIR.iterdir():
        if not subdir.is_dir():
            continue
        area, version = subdir.name.split('-')
        location_str += create_version_location(area, version, subdir)

        if not curl_text:
            curl_text = (
                '\ntest with:\n'
                f'curl -H "Host: ofm" -I http://localhost/{area}/{version}/14/8529/5975.pbf\n'
                f'curl -I https://__DOMAIN__/{area}/{version}/14/8529/5975.pbf'
            )

    location_str += create_latest_locations()

    with open(NGINX_DIR / 'location_static.conf') as fp:
        location_str += '\n' + fp.read()

    return location_str, curl_text


def create_version_location(area: str, version: str, subdir: Path) -> str:
    run_dir = DEFAULT_RUNS_DIR / area / version
    if not run_dir.is_dir():
        print(f"  {run_dir} doesn't exists, skipping")
        return ''

    tilejson_path = run_dir / 'tilejson-tiles-org.json'

    metadata_path = subdir / 'metadata.json'
    if not metadata_path.is_file():
        print(f"  {metadata_path} doesn't exists, skipping")
        return ''

    url_prefix = f'https://tiles.openfreemap.org/{area}/{version}'

    subprocess.run(
        [
            sys.executable,
            Path(__file__).parent.parent / 'metadata_to_tilejson.py',
            '--minify',
            metadata_path,
            tilejson_path,
            url_prefix,
        ],
        check=True,
    )

    return f"""
    location = /{area}/{version} {{     # no trailing slash
        alias {tilejson_path};          # no trailing slash

        expires 1w;
        default_type application/json;

        add_header 'Access-Control-Allow-Origin' '*' always;
        add_header Cache-Control public;
    }}

    location /{area}/{version}/ {{      # trailing slash
        alias {subdir}/tiles/;          # trailing slash
        try_files $uri @empty_tile;
        add_header Content-Encoding gzip;

        expires 10y;

        types {{
            application/vnd.mapbox-vector-tile pbf;
        }}

        add_header 'Access-Control-Allow-Origin' '*' always;
        add_header Cache-Control public;
    }}
    """


def create_latest_locations() -> str:
    location_str = ''

    local_version_files = OFM_CONFIG_DIR.glob('tileset_version_*.txt')
    for file in local_version_files:
        area = file.stem.split('_')[-1]
        with open(file) as fp:
            version = fp.read().strip()
        print(f'  setting latest version for {area}: {version}')

        run_dir = DEFAULT_RUNS_DIR / area / version
        tilejson_path = run_dir / 'tilejson-tiles-org.json'
        assert tilejson_path.exists()

        location_str += f"""
        location = /{area} {{          # no trailing slash
            alias {tilejson_path};       # no trailing slash

            expires 1d;
            default_type application/json;

            add_header 'Access-Control-Allow-Origin' '*' always;
            add_header Cache-Control public;
        }}
        """

    return location_str
