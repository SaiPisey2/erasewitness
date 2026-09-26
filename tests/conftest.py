import pytest

from erasewitness.scenario import Scenario, load_scenario, with_canary


@pytest.fixture
def salary() -> Scenario:
    return with_canary(load_scenario("salary"), canary="EW-004211")
