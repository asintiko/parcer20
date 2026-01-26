from parsers.operator_mapper import OperatorMapper
from database.models import OperatorReference


def seed_mappings(session):
    mappings = [
        OperatorReference(operator_name="OQ", application_name="OQ Generic", is_p2p=False, is_active=True),
        OperatorReference(operator_name="OQ P2P", application_name="OQ P2P", is_p2p=True, is_active=True),
        OperatorReference(operator_name="PAYNET", application_name="Paynet", is_p2p=False, is_active=True),
        OperatorReference(operator_name="PAY", application_name="CatchAll Pay", is_p2p=False, is_active=True),
        OperatorReference(operator_name="REGEX ONLY", application_name="RegexOnly", is_p2p=False, is_active=False),
    ]
    session.add_all(mappings)
    session.commit()


def test_operator_mapper_exact_match_wins(db_session):
    seed_mappings(db_session)
    mapper = OperatorMapper(db_session)

    result = mapper.map_operator_details("OQ P2P>TASHKENT")
    assert result is not None
    # Should pick the longer specific pattern
    assert result["application_name"] == "OQ P2P"
    assert result["is_p2p"] is True
    assert result["match_type"] == "SUBSTRING"


def test_operator_mapper_highest_priority_substring(db_session):
    seed_mappings(db_session)
    mapper = OperatorMapper(db_session)

    result = mapper.map_operator_details("PAYNET HUM2UZC")
    assert result is not None
    # Should pick longest substring "PAYNET" over "PAY"
    assert result["application_name"] == "Paynet"
    assert result["match_type"] == "SUBSTRING"


def test_operator_mapper_returns_none_for_inactive_or_no_match(db_session):
    seed_mappings(db_session)
    mapper = OperatorMapper(db_session)

    result = mapper.map_operator_details("REGEX ONLY")
    assert result is None

    result_unknown = mapper.map_operator_details("UNKNOWN OPERATOR")
    assert result_unknown is None
