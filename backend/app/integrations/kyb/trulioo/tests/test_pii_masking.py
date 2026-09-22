from app.integrations.kyb.trulioo.pii_masking import mask_entity_for_logging, mask_value


class TestR1PiiMasking:
    def test_mask_value_short(self) -> None:
        assert mask_value("ABC123456") == "ABC******"

    def test_mask_value_empty(self) -> None:
        assert mask_value("") == "***"
        assert mask_value(None) == "***"

    def test_mask_value_custom_prefix(self) -> None:
        assert mask_value("ABCDEF", prefix_len=2) == "AB****"

    def test_mask_entity_for_logging_masks_pii(self) -> None:
        masked = mask_entity_for_logging(
            legal_name="Tata Consultancy Services",
            registration_number="L22210MH1995PLC084781",
            tax_id="27AAACT2727Q1ZV",
            address="9B, Borakhola, Pune",
            country="IN",
        )
        # PII fields are masked
        assert "Tata" not in masked["legal_name"]
        assert "L22210" not in masked["registration_number"]
        assert "AAACT" not in masked["tax_id"]
        assert "Borakhola" not in masked["address"]
        # Country is NOT masked
        assert masked["country"] == "IN"
