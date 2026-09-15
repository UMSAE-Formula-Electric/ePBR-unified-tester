# latching_board_tests

Starter tester for the ePBR27 latching board. The steps here are worked
examples of each pattern you'll reuse - they are written against a board that
does not exist yet, so treat every limit and every serial command as a
placeholder to replace.

## Files

| File                  | What goes in it                                                        |
|-----------------------|------------------------------------------------------------------------|
| `parts.toml`          | Which steps run for which part number, and which results they must produce |
| `result_details.toml` | The pass/fail limit for every result id                                 |
| `config.py`           | Rail settings, waveforms, relay mapping, serial commands, timing        |
| `utils.py`            | Helpers shared by more than one step                                    |
| `tester.py`           | Top-level steps (setup, power, firmware, teardown)                      |
| `tests/latch.py`      | Latch-specific steps                                                    |
| `VERSION`             | Bump when limits or steps change - recorded in every result file        |

## Making it yours

1. **Wire the fixture, then fix `Relays` in `config.py`** so the channel names
   match what each relay actually switches.
2. **Replace the serial commands and parsers in `config.py`** with what your
   firmware prints. Test a regex against real console output before relying on it.
3. **Replace the limits in `result_details.toml`** with numbers from the design.
   The placeholders are deliberately narrow so they fail loudly rather than
   passing a bad board.
4. **Rewrite the steps.** Keep the shape - measure, then `runner.add_result()` -
   and let the limits do the judging.

## Running it

```bash
python main.py run EPBR27-LB-001 -S 0042 --simulate   # no hardware needed
python main.py run EPBR27-LB-001 -S 0042              # on the bench
python main.py run EPBR27-LB-001 -s COIL_RESISTANCE_TEST
python main.py check EPBR27-LB-001
```
