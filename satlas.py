import math
import requests
from pyproj import Transformer
from PIL import Image
from io import BytesIO
import concurrent.futures
from functools import partial
import argparse
import os
import rasterio
from rasterio.crs import CRS


def extract_geotiff_info(tif_file):
    """Extract UTM zone and corner coordinates from a GeoTIFF file."""
    if not os.path.exists(tif_file):
        raise FileNotFoundError(f"GeoTIFF file not found: {tif_file}")
    
    # Open the dataset with rasterio
    with rasterio.open(tif_file) as src:
        # Get the CRS
        crs = src.crs
        
        # Extract UTM zone from CRS
        utm_zone = None
        if crs.is_projected:
            # Try to get UTM zone from CRS
            try:
                if hasattr(crs, 'to_dict') and 'proj' in crs.to_dict() and crs.to_dict()['proj'] == 'utm':
                    utm_zone = crs.to_dict().get('zone')
                
                # If that didn't work, try parsing it from WKT
                if utm_zone is None and hasattr(crs, 'wkt'):
                    wkt = crs.wkt
                    if "UTM" in wkt and "zone" in wkt.lower():
                        parts = wkt.split()
                        for i, part in enumerate(parts):
                            if part.lower() == "zone":
                                try:
                                    utm_zone = int(parts[i+1].rstrip(',').rstrip(']'))
                                    break
                                except (IndexError, ValueError):
                                    pass
            except Exception as e:
                print(f"Error extracting UTM zone: {e}")
        
        # If UTM zone not found, try EPSG code
        if utm_zone is None and crs.is_epsg_code:
            epsg = crs.to_epsg()
            if epsg:
                # EPSG codes for UTM North: 326xx, UTM South: 327xx (xx = zone)
                if 32601 <= epsg <= 32660:
                    utm_zone = epsg - 32600
                elif 32701 <= epsg <= 32760:
                    utm_zone = epsg - 32700
        
        # Get bounds in projected coordinates
        ulx, lry, lrx, uly = src.bounds
        
        # Get image dimensions for more accurate bounds
        width = src.width
        height = src.height
        
        # Transform from pixel to projected coordinates
        transform = src.transform
        
        # Calculate precise corners
        precise_ulx, precise_uly = transform * (0, 0)
        precise_lrx, precise_lry = transform * (width, height)
        
        if utm_zone is None:
            print("Warning: Could not determine UTM zone from GeoTIFF. Using default zone 32.")
            utm_zone = 32
        
    print(f"Extracted GeoTIFF info: UTM Zone {utm_zone}")
    print(f"Upper-left: ({precise_ulx}, {precise_uly}), Lower-right: ({precise_lrx}, {precise_lry})")
    
    return utm_zone, precise_ulx, precise_uly, precise_lrx, precise_lry


def utm_to_latlon(x, y, zone=32, northern=True):
    """Convert UTM coordinates to latitude/longitude."""
    transformer = Transformer.from_crs(f"EPSG:326{zone}", "EPSG:4326", always_xy=True)
    lon, lat = transformer.transform(x, y)  # Returns (lon, lat)
    return lat, lon  # Return in (lat, lon) order


def lat_lon_to_tile_indices(lat, lon, zoom):
    """Convert latitude/longitude to tile indices for a given zoom level."""
    n = 2 ** zoom
    x_tile = int((lon + 180) / 360 * n)
    y_tile = int((1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * n)
    return x_tile, y_tile


def download_tile(x, y, z, base_url):
    """Download a single tile from the tile server."""
    url = f"{base_url}/{z}/{x}/{y}.webp"
    print(f"Attempting URL: {url}")
    response = requests.get(url)
    if response.status_code == 200:
        print(f"Successfully fetched tile: X={x}, Y={y}")
        return Image.open(BytesIO(response.content))
    else:
        print(f"Failed to fetch tile: {url} (HTTP {response.status_code})")
        return None


def stitch_tiles(tiles_dict, x_range, y_range):
    """Stitch tiles into a single large image.
    
    Args:
        tiles_dict: Dictionary of tiles with (x,y) coordinates as keys
        x_range: (min_x, max_x) tile coordinate range
        y_range: (min_y, max_y) tile coordinate range
    """
    if not tiles_dict:
        return None
        
    # Get sample tile size
    sample_tile = next(iter(tiles_dict.values()))
    width, height = sample_tile.size
    grid_width = x_range[1] - x_range[0] + 1
    grid_height = y_range[1] - y_range[0] + 1
    
    stitched = Image.new("RGB", (width * grid_width, height * grid_height))
    
    # Iterate through coordinates in correct order
    for y in range(y_range[0], y_range[1] + 1):
        for x in range(x_range[0], x_range[1] + 1):
            if (x, y) in tiles_dict:
                tile = tiles_dict[(x, y)]
                x_offset = (x - x_range[0]) * width
                y_offset = (y - y_range[0]) * height
                stitched.paste(tile, (x_offset, y_offset))
    
    return stitched


def download_tiles_parallel(x_start, x_end, y_start, y_end, zoom, base_url, max_workers=10):
    """Download multiple tiles in parallel using a thread pool."""
    tiles_dict = {}
    
    def download_single_tile(coords):
        x, y = coords
        tile = download_tile(x, y, zoom, base_url)
        if tile:
            return (x, y), tile
        return None
    
    # Create all coordinate pairs
    coords = [(x, y) for x in range(x_start, x_end + 1) 
                    for y in range(y_start, y_end + 1)]
    
    # Use ThreadPoolExecutor for parallel downloads
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all download tasks
        future_to_coords = {executor.submit(download_single_tile, coord): coord 
                          for coord in coords}
        
        # Collect results as they complete
        for future in concurrent.futures.as_completed(future_to_coords):
            result = future.result()
            if result:
                coords, tile = result
                tiles_dict[coords] = tile
    
    return tiles_dict


def get_tile_bounds_for_utm_region(ul_x, ul_y, lr_x, lr_y, zoom, utm_zone=32):
    """
    Calculate tile indices that cover a UTM region, ensuring we don't exceed the region.
    Returns minimum and maximum tile coordinates that fully contain the region.
    """
    # Convert UTM corners to lat/lon
    lat_ul, lon_ul = utm_to_latlon(ul_x, ul_y, zone=utm_zone)
    lat_lr, lon_lr = utm_to_latlon(lr_x, lr_y, zone=utm_zone)
    
    # Get tile coordinates for all corners
    x_ul, y_ul = lat_lon_to_tile_indices(lat_ul, lon_ul, zoom)
    x_lr, y_lr = lat_lon_to_tile_indices(lat_lr, lon_lr, zoom)
    
    # Find the minimum and maximum tile coordinates
    x_min = min(x_ul, x_lr)
    x_max = max(x_ul, x_lr)
    y_min = min(y_ul, y_lr)
    y_max = max(y_ul, y_lr)
    
    return x_min, x_max, y_min, y_max


def main():
    # Define command line arguments
    parser = argparse.ArgumentParser(description='Download and stitch satellite imagery tiles.')
    
    # Create a group for input source options
    input_group = parser.add_mutually_exclusive_group()
    input_group.add_argument('--geotiff', type=str, help='Path to GeoTIFF file to extract coordinates and UTM zone')
    input_group.add_argument('--dataset', choices=['set1', 'set2'], help='Predefined coordinate set to use: set1 (T32UNA) or set2')
    
    parser.add_argument('--utm-zone', type=int, help='UTM zone (only used if --geotiff is not provided)')
    parser.add_argument('--zoom', type=int, default=15, help='Zoom level (default: 15)')
    parser.add_argument('--image-type', choices=['superres', 'sentinel2'], default='superres',
                      help='Image type: superres or sentinel2 (default: superres)')
    args = parser.parse_args()
    
    # Determine coordinates and UTM zone
    if args.geotiff:
        # Extract info from GeoTIFF
        utm_zone, ul_x, ul_y, lr_x, lr_y = extract_geotiff_info(args.geotiff)
        # Generate output filename based on GeoTIFF name
        base_name = os.path.splitext(os.path.basename(args.geotiff))[0]
        file_suffix = f"{base_name}_z{utm_zone}"
    else:
        # Use predefined coordinates or default to set1
        dataset = args.dataset or 'set1'
        
        if dataset == 'set1':
            # T32UNA coordinates
            ul_x, ul_y = 605020, 5546440  # Upper-left UTM
            lr_x, lr_y = 609240, 5542220  # Lower-right UTM
            default_utm_zone = 32
        else:  # set2
            # Second set of coordinates
            ul_x, ul_y = 443040.000, 5834800.000
            lr_x, lr_y = 447220.000, 5830600.000
            default_utm_zone = 33
            
        # Use provided UTM zone or default
        utm_zone = args.utm_zone if args.utm_zone is not None else default_utm_zone
        file_suffix = f"{dataset}_z{utm_zone}"
    
    # Set zoom level
    ZOOM = args.zoom
    
    # Set base URL based on image type
    if args.image_type == 'superres':
        BASE_URL = "https://se-tile-api.allen.ai/mosaic/superres/sr2023/tci"
    else:  # sentinel2
        BASE_URL = "https://se-tile-api.allen.ai/mosaic/sentinel2/sr2023/tci"

    # Calculate tile indices that cover our UTM region
    x_start, x_end, y_start, y_end = get_tile_bounds_for_utm_region(
        ul_x, ul_y, lr_x, lr_y, ZOOM, utm_zone
    )

    print(f"UTM Bounds: Upper-left ({ul_x}, {ul_y}), Lower-right ({lr_x}, {lr_y}), Zone: {utm_zone}")
    print(f"Tile Range: X({x_start} to {x_end}), Y({y_start} to {y_end}), Zoom: {ZOOM}")

    # Download tiles in parallel
    tiles_dict = download_tiles_parallel(x_start, x_end, y_start, y_end, ZOOM, BASE_URL)

    # Handle no tiles downloaded
    if tiles_dict:
        stitched_image = stitch_tiles(tiles_dict, 
                                    (x_start, x_end),
                                    (y_start, y_end))
        if stitched_image:
            output_filename = f"stitched_image_{file_suffix}.png"
            stitched_image.save(output_filename)
            print(f"Image saved as '{output_filename}'")
    else:
        print("No tiles were downloaded.")


if __name__ == "__main__":
    main()
