# Data Source Notes

## EIA-930

- Available from 2015-07-01 onward at hourly resolution
- Some BAs have gaps; imputation strategy in `src/gridregime/clean/eia930.py`
- Interchange data revised retroactively; use latest pull where possible
- API key required: set `EIA_API_KEY` environment variable

## NOAA ISD

- Station selection: nearest station with >90% completeness for each BA centroid
- Quality flags: use only `quality_code in [0,1,5]`
- Missing obs filled by linear interpolation up to 3h gaps; longer gaps flagged

## PJM Dataminer2

- Emergency procedure declarations available as event markers
- Load forecast accuracy degrades >48h ahead; use with caution
- Historical data before 2016 requires separate archive request

## Historical Events

### 2003 Northeast Blackout
- EIA-930 not available; use FERC/DOE investigation reports
- Hourly load reconstructed from NYISO/PJM archives
- See NERC 2004 report for detailed timeline

### 2014 Polar Vortex
- EIA-930 available but with gaps in early hours
- PJM emergency action log downloaded separately
- Weather data from NOAA GHCND daily + hourly ISD blended
