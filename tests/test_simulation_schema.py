import uuid

import pytest
from fastapi import FastAPI
from pydantic import ValidationError

from app.routers.simulation import router
from app.schemas.simulation import SimulationRequest


@pytest.mark.parametrize('mode', ['single', 'pipeline'])
def test_existing_request_modes(mode):
    body = SimulationRequest(build_id=uuid.uuid4(), mode=mode)
    assert body.mode == mode and body.max_cycles == 2000


@pytest.mark.parametrize('fields', [
    {}, {'build_id': str(uuid.uuid4()), 'simulation_token': 'both'},
    {'simulation_token': 'test-only', 'mode': 'unknown'},
    *[{'simulation_token': 'test-only', 'max_cycles': value} for value in (0, 2001, True, 1.5)],
])
def test_invalid_requests(fields):
    with pytest.raises(ValidationError):
        SimulationRequest(**fields)


def test_openapi_uses_schema_models_and_existing_endpoint():
    app = FastAPI()
    app.include_router(router)
    operation = app.openapi()['paths']['/api/v1/simulation/run']['post']
    assert operation['requestBody']['content']['application/json']['schema']['$ref'].endswith('/SimulationRequest')
    assert operation['responses']['200']['content']['application/json']['schema']['$ref'].endswith('/SimulationResponse')
