# Satellite Imagery Tile Downloader

This tool downloads and stitches satellite imagery tiles from the Allen AI tile server based on coordinates extracted from GeoTIFF files or predefined coordinate sets.

## Features

- Extract UTM zone and coordinates directly from GeoTIFF files
- Support for multiple UTM zones
- Download tiles in parallel for faster processing
- Stitch tiles into a single continuous image
- Choose between super-resolution and standard Sentinel-2 imagery
- Adjustable zoom level for different resolutions

## Installation

1. Clone this repository:
   ```
   git clone <repository-url>
   cd <repository-directory>
   ```

2. Create a virtual environment (optional but recommended):
   ```
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. Install the required dependencies:
   ```
   pip install -r requirements.txt
   ```

## Usage

### Basic Usage

The script can extract coordinates and UTM zone directly from a GeoTIFF file:

```
python main.py --geotiff <path-to-geotiff-file>
```

### Command-line Options

```
python main.py [-h] [--geotiff GEOTIFF | --dataset {set1,set2}] [--utm-zone UTM_ZONE] [--zoom ZOOM] [--image-type {superres,sentinel2}]
```

- `--geotiff`: Path to a GeoTIFF file to extract coordinates and UTM zone from
- `--dataset`: Use predefined coordinates (set1 for T32UNA or set2 for T33UVU)
- `--utm-zone`: Manually specify the UTM zone (only used if not using --geotiff)
- `--zoom`: Set the zoom level (default: 15)
- `--image-type`: Choose image type - superres or sentinel2 (default: superres)

### Examples

1. Download super-resolution imagery using coordinates from a GeoTIFF file:
   ```
   python main.py --geotiff S2L2A_T32UNA-20240828-u6d7139f_TCI.tif
   ```

2. Download standard Sentinel-2 imagery with the same coordinates:
   ```
   python main.py --geotiff S2L2A_T32UNA-20240828-u6d7139f_TCI.tif --image-type sentinel2
   ```

3. Use higher resolution (zoom level 16):
   ```
   python main.py --geotiff S2L2A_T32UNA-20240828-u6d7139f_TCI.tif --zoom 16
   ```

4. Use predefined coordinate set with specific UTM zone:
   ```
   python main.py --dataset set2 --utm-zone 33
   ```

## Output

The script will create a PNG image in the current directory with a filename based on the input:
- When using a GeoTIFF: `stitched_image_<geotiff-filename>_z<utm-zone>.png`
- When using predefined sets: `stitched_image_<set-name>_z<utm-zone>.png`

Currently, the filename doesn't indicate whether the image is from super-resolution or Sentinel-2 source. To make this clearer, you could modify the code to include the image type in the filename:

```python
# In main.py, modify the output filename line:
output_filename = f"stitched_image_{file_suffix}_{args.image_type}.png"
```

This would result in filenames like:
- `stitched_image_S2L2A_T32UNA-20240828-u6d7139f_TCI_z32_superres.png`
- `stitched_image_set2_z33_sentinel2.png`

## Notes

- The script requires an internet connection to access the Allen AI tile server.
- Higher zoom levels result in more detailed imagery but require downloading more tiles.
- The super-resolution option provides enhanced imagery compared to the standard Sentinel-2 option. 