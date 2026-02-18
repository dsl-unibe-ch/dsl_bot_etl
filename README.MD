## Prerequisite
<details>
<summary>Click to expand</summary>

- Install Python 3.12.11

</details>

## Configure the Python environment
<details>
<summary>Click to expand</summary>

- Install `uv`: 

```bash
pip install uv==0.8.14
```

- Create virtual environment: 
```bash
uv venv .venv --python 3.12.11
```

- Activate with: 
```bash
source .venv/bin/activate
```

- Install the libraries (including dev): 
```bash
uv pip install -r pyproject.toml
```

- Install pre-commit: 
```bash
pre-commit install
```

</details>

## Configure the Environment Variables
<details>

There are three levels of environment variables in this project.
1. `.env.etl` : This file contains the environment to start the process of downloading the env secrets of the app from Azure. Perform the following steps to create the file.
    1. Copy the `.env.etl.example` file into `env.etl`.  
    2. Populate the variables in `.env.etl` by looking up the corresponding values in the storage resource inside the `global` resource group inside the subscription, for example `rg-kb-global-001`. 
2. `.env.dev.app`: This file contains the env variables for the dev resource group.  To download this file, 
    ```bash
    make copy-secrets-from-container ENV=dev
    ```
3. `.env.prod.app`: This file contains the env variables for the prod resource group.  To download this file, 
    ```bash
    make copy-secrets-from-container ENV=prod
    ```



</details>