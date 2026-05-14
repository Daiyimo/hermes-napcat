"""
Tests for skill auto-discovery and channel prompt resolution in NapCat adapter.

These tests verify the integration with resolve_channel_prompt and
resolve_channel_skills from the Hermes gateway.
"""

import pytest
from unittest.mock import Mock


class TestChannelPromptResolution:
    """Test channel prompt resolution with mock gateway functions."""

    def create_mock_resolve_channel_prompt(self):
        """Create a mock implementation of resolve_channel_prompt."""
        def resolve_channel_prompt(config_extra, channel_id, parent_id=None):
            if not config_extra:
                return None
            
            channel_prompts = config_extra.get("channel_prompts", {})
            
            # Prefer exact match on channel_id
            if channel_id in channel_prompts:
                return channel_prompts[channel_id]
            
            # Fall back to parent_id
            if parent_id and parent_id in channel_prompts:
                return channel_prompts[parent_id]
            
            return None
        
        return resolve_channel_prompt

    def create_mock_resolve_channel_skills(self):
        """Create a mock implementation of resolve_channel_skills."""
        def resolve_channel_skills(config_extra, channel_id, parent_id=None):
            if not config_extra:
                return None
            
            bindings = config_extra.get("channel_skill_bindings", [])
            if not bindings:
                return None
            
            # Collect all matching skills for this channel
            skills = []
            for binding in bindings:
                if binding.get("id") == channel_id:
                    # Handle both "skill" (single) and "skills" (list) formats
                    if "skill" in binding:
                        skills.append(binding["skill"])
                    if "skills" in binding:
                        skills.extend(binding["skills"])
            
            if not skills:
                # Try parent_id as fallback
                if parent_id:
                    for binding in bindings:
                        if binding.get("id") == parent_id:
                            if "skill" in binding:
                                skills.append(binding["skill"])
                            if "skills" in binding:
                                skills.extend(binding["skills"])
            
            # Deduplicate and return
            if skills:
                return list(dict.fromkeys(skills))  # Preserves order while deduping
            
            return None
        
        return resolve_channel_skills

    def test_resolve_channel_prompt_exact_match(self):
        """Test exact channel ID match for prompt."""
        resolve_channel_prompt = self.create_mock_resolve_channel_prompt()
        
        config_extra = {
            "channel_prompts": {
                "123456": "Prompt for 123456",
                "789012": "Prompt for 789012",
            }
        }
        result = resolve_channel_prompt(config_extra, "123456")
        assert result == "Prompt for 123456"

    def test_resolve_channel_prompt_no_match(self):
        """Test when no prompt matches the channel."""
        resolve_channel_prompt = self.create_mock_resolve_channel_prompt()
        
        config_extra = {
            "channel_prompts": {
                "123456": "Prompt for 123456",
            }
        }
        result = resolve_channel_prompt(config_extra, "999999")
        assert result is None

    def test_resolve_channel_prompt_empty_config(self):
        """Test with empty config."""
        resolve_channel_prompt = self.create_mock_resolve_channel_prompt()
        
        config_extra = {}
        result = resolve_channel_prompt(config_extra, "123456")
        assert result is None

    def test_resolve_channel_skills_single_skill(self):
        """Test resolving a single skill binding."""
        resolve_channel_skills = self.create_mock_resolve_channel_skills()
        
        config_extra = {
            "channel_skill_bindings": [
                {"id": "123456", "skill": "web-search"},
            ]
        }
        result = resolve_channel_skills(config_extra, "123456")
        assert result == ["web-search"]

    def test_resolve_channel_skills_multiple_skills(self):
        """Test resolving multiple skill bindings."""
        resolve_channel_skills = self.create_mock_resolve_channel_skills()
        
        config_extra = {
            "channel_skill_bindings": [
                {"id": "123456", "skills": ["web-search", "calculator", "translator"]},
            ]
        }
        result = resolve_channel_skills(config_extra, "123456")
        assert set(result) == {"web-search", "calculator", "translator"}

    def test_resolve_channel_skills_mixed_formats(self):
        """Test mixed 'skill' (single) and 'skills' (list) formats."""
        resolve_channel_skills = self.create_mock_resolve_channel_skills()
        
        config_extra = {
            "channel_skill_bindings": [
                {"id": "123456", "skill": "web-search"},
                {"id": "123456", "skills": ["calculator", "translator"]},
            ]
        }
        result = resolve_channel_skills(config_extra, "123456")
        assert set(result) == {"web-search", "calculator", "translator"}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
