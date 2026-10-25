from importlib.resources import files

from network_simulation.configuration import POCConfig, PromptConfig
from network_simulation.validation.checkov_validator import CheckovValidator
from validation.checkov_validator import CheckovValidator as LegacyCheckovValidator


def test_default_prompts_are_package_resources():
    for filename in ("prompt_b1.md", "prompt_t1.md", "prompt_iterative.md"):
        assert files("network_simulation").joinpath("prompts", filename).is_file()
    assert PromptConfig().template_directory is None
    assert POCConfig().prompts.system_prompt_b1


def test_legacy_adapter_reexports_packaged_implementation():
    assert LegacyCheckovValidator is CheckovValidator
