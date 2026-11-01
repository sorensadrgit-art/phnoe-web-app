"""Public strict-JSON semantics preserved by the capacity correction."""
import json
import math
import sys
import unittest
from unittest.mock import patch

import session_contract


class StrictJsonParserTests(unittest.TestCase):
    def test_scalar_values_and_exact_types_for_all_input_forms(self):
        cases = (
            ("0", 0, int), ("-0", 0, int), ("12345678901234567890", 12345678901234567890, int),
            ("1.25", 1.25, float), ("1e2", 100.0, float),
            ("true", True, bool), ("false", False, bool), ("null", None, type(None)),
            ('"雪\\ntext"', "雪\ntext", str),
            ("[]", [], list), ("{}", {}, dict),
        )
        for text, expected, expected_type in cases:
            for form in (text, text.encode("utf-8"), bytearray(text, "utf-8")):
                with self.subTest(text=text, input_type=type(form).__name__):
                    actual = session_contract.strict_json_loads(form)
                    self.assertEqual(actual, expected)
                    self.assertIs(type(actual), expected_type)

    def test_nested_values_types_and_object_order_for_all_input_forms(self):
        text = '{"雪":[1,1.0,true,false,null,"value",{},[]],"last":{"x":2}}'
        expected = {"雪": [1, 1.0, True, False, None, "value", {}, []], "last": {"x": 2}}
        for form in (text, text.encode("utf-8"), bytearray(text, "utf-8")):
            with self.subTest(input_type=type(form).__name__):
                actual = session_contract.strict_json_loads(form)
                self.assertEqual(actual, expected)
                self.assertEqual(list(actual), ["雪", "last"])
                self.assertEqual([type(item) for item in actual["雪"]],
                                 [int, float, bool, bool, type(None), str, dict, list])
                self.assertIs(type(actual["last"]["x"]), int)

    def test_finite_extrema_underflow_and_negative_zero(self):
        cases = (
            ("1.7976931348623157e308", sys.float_info.max),
            ("-1.7976931348623157e308", -sys.float_info.max),
            ("2.2250738585072014e-308", sys.float_info.min),
            ("5e-324", float.fromhex("0x0.0000000000001p-1022")),
            ("1e-999", 0.0), ("-1e-999", -0.0), ("-0.0", -0.0),
        )
        for text, expected in cases:
            with self.subTest(text=text):
                actual = session_contract.strict_json_loads(text)
                self.assertIs(type(actual), float)
                self.assertEqual(actual, expected)
                self.assertTrue(math.isfinite(actual))
                self.assertEqual(math.copysign(1.0, actual), math.copysign(1.0, expected))

    def test_nonfinite_literals_and_exponent_overflows(self):
        for token in ("NaN", "Infinity", "-Infinity", "1e999", "-1e999", "1E+999", "-1E+999"):
            for text, path in ((token, "$"), ('{"a":[0,' + token + ']}', "$.a[1]")):
                for form in (text, text.encode("utf-8"), bytearray(text, "utf-8")):
                    with self.subTest(token=token, path=path, input_type=type(form).__name__):
                        expected = ("JSON_INVALID: nonfinite number " + token if token in
                                    ("NaN", "Infinity", "-Infinity") else
                                    "JSON_INVALID: nonfinite number at " + path)
                        with self.assertRaises(ValueError) as caught:
                            session_contract.strict_json_loads(form)
                        self.assertEqual(str(caught.exception), expected)

    def test_first_depth_first_overflow_path_preserves_unusual_keys(self):
        cases = (
            ('{"later":[0,{"a.b[0] 雪\\n\\\"":-1e999}],"earlier":1e999}',
             '$.later[1].a.b[0] 雪\n"'),
            ('[{"":1e999},-1e999]', "$[0]."),
            ('{"z":{"second":1e999},"a":-1e999}', "$.z.second"),
            ('[[0,1e999],-1e999]', "$[0][1]"),
        )
        for text, path in cases:
            with self.subTest(text=text):
                with self.assertRaises(ValueError) as caught:
                    session_contract.strict_json_loads(text)
                self.assertEqual(str(caught.exception), "JSON_INVALID: nonfinite number at " + path)

    def test_decoder_errors_precede_post_decode_overflow_traversal(self):
        cases = (
            ('{"overflow":1e999,"x":0,"x":1}', "JSON_INVALID: duplicate key x"),
            ('{"overflow":1e999,"nested":{"雪":0,"雪":1}}', "JSON_INVALID: duplicate key 雪"),
            ('[1e999,NaN]', "JSON_INVALID: nonfinite number NaN"),
            ('[1e999,Infinity]', "JSON_INVALID: nonfinite number Infinity"),
            ('[1e999,-Infinity]', "JSON_INVALID: nonfinite number -Infinity"),
            ('{"x":0,"x":1,"later":NaN}', "JSON_INVALID: nonfinite number NaN"),
        )
        for text, expected in cases:
            with self.subTest(text=text):
                with self.assertRaises(ValueError) as caught:
                    session_contract.strict_json_loads(text)
                self.assertEqual(str(caught.exception), expected)
        for text in ('[1e999,]', '{"overflow":1e999', '1e999 trailing'):
            with self.subTest(malformed=text):
                with self.assertRaises(json.JSONDecodeError) as native:
                    json.loads(text)
                with self.assertRaises(json.JSONDecodeError) as strict:
                    session_contract.strict_json_loads(text)
                self.assertEqual((strict.exception.msg, strict.exception.doc, strict.exception.pos),
                                 (native.exception.msg, native.exception.doc, native.exception.pos))

    def test_replaced_decoder_still_checks_nonfinite_and_preserves_exceptions(self):
        for number in (float("nan"), float("inf"), float("-inf")):
            for value, path in ((number, "$"), ({"雪": [0, number], "later": float("inf")}, "$.雪[1]")):
                with self.subTest(number=number, path=path):
                    with (patch.object(session_contract.json, "loads", return_value=value),
                          self.assertRaises(ValueError) as caught):
                        session_contract.strict_json_loads("null")
                    self.assertEqual(str(caught.exception), "JSON_INVALID: nonfinite number at " + path)
        for error in (ValueError("decoder failure"), OSError("decoder I/O failure"),
                      UnicodeError("decoder encoding failure"), json.JSONDecodeError("bad", "x", 0)):
            with self.subTest(error_type=type(error).__name__):
                with (patch.object(session_contract.json, "loads", side_effect=error),
                      self.assertRaises(type(error)) as caught):
                    session_contract.strict_json_loads("null")
                self.assertIs(caught.exception, error)


if __name__ == "__main__":
    unittest.main()
