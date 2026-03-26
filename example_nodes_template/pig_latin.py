import re
from typing import Any

from griptape_nodes.exe_types.core_types import Parameter, ParameterMode
from griptape_nodes.exe_types.node_types import ControlNode


# Control Nodes import the ControlNode class.
class ConvertToPigLatin(ControlNode):
    def __init__(self, name: str, metadata: dict[str, Any] | None = None, **kwargs) -> None:
        node_metadata = {"category": "ControlNodes", "description": "Change to pig latin"}
        if metadata:
            node_metadata.update(metadata)
        super().__init__(name=name, metadata=node_metadata, **kwargs)

        self.add_parameter(
            Parameter(
                name="input",
                input_types=["str"],
                type="str",
                output_type="str",
                tooltip="Input string",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                ui_options={"placeholder_text": "Input text here", "multiline": True},
            )
        )
        self.add_parameter(
            Parameter(
                name="pig_latin",
                output_type="str",
                type="str",
                tooltip="The last name of the user",
                # Specifying allowed_modes determines how the parameter can be used. Can it receive inputs, send outputs, or be modified in the node?
                allowed_modes={ParameterMode.OUTPUT},
                ui_options={"placeholder_text": "Input text here", "multiline": True},
            )
        )

    def process(self) -> None:
        # All of the current values of a parameter are stored on self.parameter_values (If they have an INPUT or PROPERTY)
        input_val = self.parameter_values["input"]
        pig_latin = to_pig_latin(input_val)
        self.parameter_output_values["pig_latin"] = pig_latin
        # The node is complete!


def to_pig_latin(text: str) -> str:
    if not text:
        return ""

    words = text.split()
    pig_latin_words = []

    for word in words:
        # Skip punctuation-only "words"
        if not re.search("[a-zA-Z]", word):
            pig_latin_words.append(word)
            continue

        # Find leading punctuation
        leading_punct_match = re.match(r"^([^a-zA-Z]*)", word)
        leading_punct = leading_punct_match.group(0) if leading_punct_match else ""

        # Find trailing punctuation
        trailing_punct_match = re.search(r"([^a-zA-Z]*)$", word)
        trailing_punct = trailing_punct_match.group(0) if trailing_punct_match else ""

        # Extract the actual word without punctuation
        actual_word = word[len(leading_punct) : len(word) - len(trailing_punct)]
        if not actual_word:
            pig_latin_words.append(word)
            continue

        # Convert the word based on whether it starts with a vowel
        first_char = actual_word[0].lower()

        if first_char in "aeiou":
            # Word starts with a vowel
            pig_latin_word = actual_word + "way"
        else:
            # Find the first vowel
            vowel_match = re.search("[aeiou]", actual_word.lower())

            if not vowel_match:
                # No vowels found, just add "ay"
                pig_latin_word = actual_word + "ay"
            else:
                # Move consonants before the first vowel to the end and add "ay"
                first_vowel_index = vowel_match.start()
                prefix = actual_word[:first_vowel_index]
                suffix = actual_word[first_vowel_index:]
                pig_latin_word = suffix + prefix + "ay"

        # Preserve the case of the first letter
        if actual_word[0].isupper():
            pig_latin_word = pig_latin_word[0].upper() + pig_latin_word[1:].lower()

        # Reconstruct the word with punctuation
        pig_latin_words.append(leading_punct + pig_latin_word + trailing_punct)

    # Join the words back together
    return " ".join(pig_latin_words)
