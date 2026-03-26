# Griptape Nodes: Foundry Nuke Library

Welcome to the Griptape Nodes Foundry Nuke Library.
This library contains nodes, templates, and publishing capabilities for working with [Foundry Nuke](https://www.foundry.com/products/nuke-family)

### Key Configuration Features

Copy [.env.example](.env.example) to `.env` and replace the environment variables with the ones you want to use.


### Install the Library

1. **Download the library files** to your Griptape Nodes libraries directory:

   ```bash
   # Navigate to your Griptape Nodes libraries directory
   cd `gtn config show workspace_directory`

   # Clone or download your library
   git clone https://github.com/your-username/your-library-name.git
   ```

2. **Add the library** in the Griptape Nodes Editor:

   - Open the Settings menu and navigate to the _Libraries_ settings
   - Click on _+ Add Library_ at the bottom of the settings panel
   - Enter the path to the library JSON file: **your Griptape Nodes Workspace directory**`/your-library-name/griptape-nodes-library.json`
   - You can check your workspace directory with `gtn config show workspace_directory`
   - Close the Settings Panel
   - Click on _Refresh Libraries_

3. **Verify installation** by checking that your custom nodes appear in the Griptape Nodes interface in your defined category.

## 🎯 Example Usage

### Here is an example flow that you could make with the provided nodes:

## 🔍 Troubleshooting

### Common Issues

#### Library Not Appearing

- Verify the JSON file path is correct
- Check that the JSON syntax is valid (no trailing commas, proper quotes)
- Ensure the library was refreshed after adding

#### Node Import Errors

- Check that all required dependencies are listed in the JSON
- Verify Python file paths are correct relative to the JSON file
- Ensure class names match exactly between Python files and JSON

#### Missing API Keys

- Configure secrets in Settings > API Keys & Secrets
- Use the exact key names specified in `secrets_to_register`
- Restart Griptape Nodes after adding new secrets

## 📚 Additional Resources

### Documentation

- [Griptape Nodes Documentation](https://github.com/griptape-ai/griptape-nodes)
- [Griptape Framework](https://github.com/griptape-ai/griptape)
- [Node Development Examples](example_nodes_template/)

### Community

- [Griptape Discord](https://discord.gg/griptape)
- [GitHub Discussions](https://github.com/griptape-ai/griptape-nodes/discussions)

### Example Libraries

- [Griptape Nodes Directory](https://github.com/griptape-ai/griptape-nodes-directory)

## 📄 License

This template is provided under the Apache License 2.0. Your custom library can use any license you choose.

---

Happy building! 🚀
