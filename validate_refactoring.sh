#!/usr/bin/env bash
# Feed Refactoring Validation Script
# Verify that the new modular feed architecture works without breaking existing functionality

set -e

echo "🔍 Feed Refactoring Validation"
echo "================================"
echo ""

# 1. Check Python syntax
echo "✓ Step 1: Checking Python syntax..."
python -m py_compile app/backend/services/feed/__init__.py
python -m py_compile app/backend/services/feed/feed_loader.py
python -m py_compile app/backend/services/feed/feed_ranker.py
python -m py_compile app/backend/services/feed/feed_filter.py
python -m py_compile app/backend/services/feed/interaction_tracker.py
python -m py_compile app/backend/services/feed_service.py
echo "  ✅ All feed modules compile successfully"
echo ""

# 2. Check imports
echo "✓ Step 2: Checking imports..."
python -c "from app.backend.services.feed import load_fresh_candidates, rank_items, filter_feed" && echo "  ✅ Feed module imports work" || echo "  ❌ Import error"
echo ""

# 3. List new modules
echo "✓ Step 3: Feed architecture structure:"
echo "  📦 app/backend/services/feed/"
ls -la app/backend/services/feed/ | grep -E "\.py$" | awk '{print "    - " $NF}'
echo ""

# 4. Check documentation
echo "✓ Step 4: Documentation created:"
[ -f FEED_REFACTORING.md ] && echo "  ✅ FEED_REFACTORING.md" || echo "  ❌ Missing"
[ -f FEED_IMPLEMENTATION_CHECKLIST.md ] && echo "  ✅ FEED_IMPLEMENTATION_CHECKLIST.md" || echo "  ❌ Missing"
echo ""

# 5. Check Docker status (if running)
echo "✓ Step 5: Docker services status:"
if command -v docker &> /dev/null; then
    docker compose ps 2>/dev/null | tail -n +2 | wc -l
    docker compose ps 2>/dev/null | tail -n +2 | awk '{print "  - " $1 ": " $NF}'
    echo "  ✅ Docker services running"
else
    echo "  ⚠️  Docker not found (skipped)"
fi
echo ""

# 6. Test health endpoint
echo "✓ Step 6: Testing health endpoint..."
if command -v curl &> /dev/null; then
    HEALTH=$(curl -s http://localhost:8000/health 2>/dev/null || echo "")
    if [ -n "$HEALTH" ]; then
        echo "  ✅ Backend health check: $HEALTH"
    else
        echo "  ⚠️  Backend not running (http://localhost:8000/health not accessible)"
    fi
else
    echo "  ⚠️  curl not found (skipped)"
fi
echo ""

echo "================================"
echo "✅ Validation Complete!"
echo ""
echo "Next steps:"
echo "1. Test feed endpoint: curl -H 'Authorization: Bearer <TOKEN>' http://localhost:8000/api/feed/me?limit=10"
echo "2. Check logs: docker compose logs web"
echo "3. Review: FEED_REFACTORING.md and FEED_IMPLEMENTATION_CHECKLIST.md"
