# Prints an MCP server entry for your agent (stdio). Paste it into the agent's MCP configuration.
param([string]$ApiKey = "dev-agent-key")
$root = Split-Path -Parent $PSScriptRoot
$cfg = @{
  mcpServers = @{
    "knowledge-topology" = @{
      command = "$root\backend\.venv\Scripts\kt.exe"
      args    = @("mcp")
      env     = @{ KT_MCP_API_KEY = $ApiKey; KT_DATA_DIR = "$root\backend\data"; KT_DATABASE_URL = "sqlite:///$($root -replace '\\','/')/backend/data/kt.db" }
    }
  }
}
$cfg | ConvertTo-Json -Depth 5
