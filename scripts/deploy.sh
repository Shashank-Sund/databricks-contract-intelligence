#!/bin/bash

# Deploy to Databricks Apps
# Requires DATABRICKS_APP_NAME and WORKSPACE_SOURCE_PATH in .env.local

set -e

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🚀 Databricks App Deployment"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ============================================================
# Check Required Dependencies
# ============================================================

MISSING_DEPS=()
INSTALL_COMMANDS=()

# Check for uv (Python package manager)
if ! command -v uv &> /dev/null; then
  MISSING_DEPS+=("uv")
  INSTALL_COMMANDS+=("curl -LsSf https://astral.sh/uv/install.sh | sh")
fi

# Check for bun (JavaScript runtime)
if ! command -v bun &> /dev/null; then
  MISSING_DEPS+=("bun")
  INSTALL_COMMANDS+=("curl -fsSL https://bun.sh/install | bash")
fi

# Check for databricks CLI
if ! command -v databricks &> /dev/null; then
  MISSING_DEPS+=("databricks")
  INSTALL_COMMANDS+=("curl -fsSL https://raw.githubusercontent.com/databricks/setup-cli/main/install.sh | sh")
fi

# If there are missing dependencies, prompt user
if [ ${#MISSING_DEPS[@]} -gt 0 ]; then
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "📦 Missing Required Dependencies"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo ""
  echo "The following tools are required but not installed:"
  echo ""
  for i in "${!MISSING_DEPS[@]}"; do
    echo "  ❌ ${MISSING_DEPS[$i]}"
    echo "     Install: ${INSTALL_COMMANDS[$i]}"
    echo ""
  done

  read -p "Would you like to install them now? (y/N) " -n 1 -r
  echo ""

  if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo ""
    for i in "${!MISSING_DEPS[@]}"; do
      echo "📥 Installing ${MISSING_DEPS[$i]}..."
      eval "${INSTALL_COMMANDS[$i]}"
      if [ $? -eq 0 ]; then
        echo "✅ ${MISSING_DEPS[$i]} installed successfully"
      else
        echo "❌ Failed to install ${MISSING_DEPS[$i]}"
        exit 1
      fi
      echo ""
    done

    # Reload shell environment to pick up new installations
    echo "🔄 Reloading shell environment..."
    export PATH="$HOME/.local/bin:$HOME/.bun/bin:$PATH"
    echo ""
  else
    echo ""
    echo "Please install the missing dependencies and try again."
    exit 1
  fi
fi

echo "✅ All dependencies installed (uv, bun, databricks)"
echo ""

# ============================================================
# Project Root Check
# ============================================================

# Ensure script is run from project root
if [ ! -f "pyproject.toml" ] || [ ! -d "client" ]; then
  echo "❌ Error: This script must be run from the project root directory"
  echo "Current directory: $(pwd)"
  echo "Run: cd /path/to/databricks-genai-app-template && ./scripts/deploy.sh"
  exit 1
fi

# ============================================================
# Environment Configuration
# ============================================================

# Load environment variables from .env.local if it exists.
if [ -f .env.local ]
then
  set -a
  source .env.local
  set +a
fi

# If WORKSPACE_SOURCE_PATH is not set throw an error.
if [ -z "$WORKSPACE_SOURCE_PATH" ]
then
  echo "WORKSPACE_SOURCE_PATH is not set. Please set to the /Workspace/Users/{username}/{app-name} in .env.local."
  exit 1
fi

if [ -z "$DATABRICKS_APP_NAME" ]
then
  echo "DATABRICKS_APP_NAME is not set. Please set to the name of the app in .env.local."
  exit 1
fi

if [ -z "$DATABRICKS_CONFIG_PROFILE" ]
then
  DATABRICKS_CONFIG_PROFILE="DEFAULT"
fi

# ============================================================
# Databricks Authentication
# ============================================================

echo "🔐 Verifying Databricks authentication..."

# Authenticate with Databricks CLI using the host from environment
if [ -n "$DATABRICKS_HOST" ]; then
  databricks auth login --host "$DATABRICKS_HOST" 2>/dev/null || true
fi

# Verify authentication by testing a simple API call
if ! databricks auth describe --profile "$DATABRICKS_CONFIG_PROFILE" &> /dev/null; then
  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "❌ Databricks Authentication Failed"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo ""
  echo "Unable to authenticate with Databricks."
  echo ""
  echo "Please ensure one of the following:"
  echo "  1. DATABRICKS_HOST and DATABRICKS_TOKEN are set in .env.local"
  echo "  2. Or run: databricks auth login --host <your-workspace-url>"
  echo ""
  exit 1
fi

echo "✅ Databricks authentication verified"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📦 Building Application"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Generate requirements.txt from pyproject.toml
echo "🐍 Generating requirements.txt from pyproject.toml..."
uv run python scripts/generate_server_requirements.py

# Build frontend locally before deployment
echo ""
echo "⚛️  Building Vite frontend..."
cd client
bun install
bun run build
cd ..
echo "✅ Frontend build complete"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🚀 Deploying to Databricks Apps"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Echo current working directory
echo "Current Working Directory:"
echo ""
pwd
echo ""

# Sync code to workspace
echo "📤 Syncing code to workspace..."
databricks sync . "$WORKSPACE_SOURCE_PATH" \
  --exclude-from .databricksignore \
  --include "client/out/**" \
  --full \
  --profile "$DATABRICKS_CONFIG_PROFILE"

# Deploy app
echo ""
echo "🎯 Deploying app: $DATABRICKS_APP_NAME..."
databricks apps deploy $DATABRICKS_APP_NAME \
  --source-code-path "$WORKSPACE_SOURCE_PATH" \
  --profile "$DATABRICKS_CONFIG_PROFILE"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Deployment Complete"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Verify deployment
echo "📊 Verifying deployment..."
APP_STATUS=$(databricks apps list --profile "$DATABRICKS_CONFIG_PROFILE" | grep "$DATABRICKS_APP_NAME" || echo "")

if [ -n "$APP_STATUS" ]; then
  echo "✅ App is deployed"
  echo ""
  echo "$APP_STATUS"
  echo ""
  echo "📋 Next Steps:"
  echo ""
  echo "  1. Access App:"
  echo "     • Navigate to Compute → Apps in Databricks workspace"
  echo "     • Click '$DATABRICKS_APP_NAME' to open the app"
  echo ""
  echo "  2. Monitor App:"
  echo "     • Logs: Click 'Logs' tab or visit {app-url}/logz"
  echo "     • Health: Visit {app-url}/api/health"
  echo ""
  echo "  3. Test Functionality:"
  echo "     • Send a test message in the chat interface"
  echo "     • Verify agent responses and markdown rendering"
  echo "     • Check logs for any errors"
  echo ""
else
  echo "⚠️  App not found - deployment may have failed"
  echo ""
  echo "Debugging steps:"
  echo "  1. Run: databricks apps list --profile $DATABRICKS_CONFIG_PROFILE"
  echo "  2. Verify DATABRICKS_APP_NAME in .env.local"
  echo "  3. Check workspace permissions for app deployment"
  echo "  4. Review deployment logs above for errors"
  echo ""
fi
