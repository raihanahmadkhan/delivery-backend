from fastapi import APIRouter, HTTPException, UploadFile, File
from models.schemas import PresetsListResponse, PointsResponse, DeliveryPoint
from services.presets import get_preset, available_presets
from utils.csv_parser import parse_csv
router = APIRouter(prefix='/api', tags=['Data'])

@router.get('/presets', response_model=PresetsListResponse, summary='List available preset datasets')
async def list_presets() -> PresetsListResponse:
    return PresetsListResponse(available=available_presets())

@router.get('/presets/{name}', response_model=PointsResponse, summary='Load a preset dataset by name')
async def load_preset(name: str) -> PointsResponse:
    try:
        points_raw = get_preset(name)
        points = [DeliveryPoint(**p) for p in points_raw]
        return PointsResponse(points=points)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@router.post('/upload', response_model=PointsResponse, summary='Upload a CSV file of delivery points')
async def upload_csv(file: UploadFile=File(...)) -> PointsResponse:
    if not file.filename or not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail='Only .csv files are accepted.')
    content = await file.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail='File too large. Maximum size is 5 MB.')
    try:
        points_raw = parse_csv(content)
        points = [DeliveryPoint(**p) for p in points_raw]
        return PointsResponse(points=points)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc