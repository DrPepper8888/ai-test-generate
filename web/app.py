"""
Python 原生 Web 服务 — 使用 http.server 标准库
无任何第三方依赖

P2 第二阶段：用例标签与基础 UI 迭代
"""
import json
import os
import sys
import datetime
import uuid
import urllib.request
import urllib.parse
import base64
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from socketserver import ThreadingMixIn

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.workflow.pipeline import GenerationPipeline
from src.api.llm_client import LLMClient, _detect_provider
from src.tools.importer import import_file_to_cases
from src.memory.memory_store import MemoryStore

CONFIG_PATH = PROJECT_ROOT / "config.json"
memory_store = MemoryStore(PROJECT_ROOT / "data")


def load_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {
            "llm": {
                "base_url": "https://api.openai.com",
                "model_name": "gpt-4o-mini",
                "api_key": "",
                "timeout": 60,
                "max_tokens": 4000,
                "temperature": 0.7,
            },
            "generation": {
                "default_count": 7,
                "min_count": 3,
                "max_count": 20,
                "batch_size": 20,
                "max_retries": 2,
            },
            "storage": {
                "history_file": "data/history.json",
                "feedback_file": "data/feedback.json",
            },
        }


def save_config(cfg: dict):
    CONFIG_PATH.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
    )


config = load_config()
pipeline = GenerationPipeline(config)
memory_store = MemoryStore(PROJECT_ROOT / "data")


def rebuild_pipeline():
    global pipeline
    pipeline = GenerationPipeline(config)


# 会话存储（持久化到文件）
sessions = {}
SESSIONS_DIR = PROJECT_ROOT / "data" / "memory" / "sessions"
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


def _session_file_path(session_id: str) -> Path:
    return SESSIONS_DIR / f"{session_id}.json"


def save_session_to_file(session_id: str):
    session = sessions.get(session_id)
    if session:
        _session_file_path(session_id).write_text(
            json.dumps(session, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )


def load_session_from_file(session_id: str) -> dict:
    path = _session_file_path(session_id)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return None


def new_session() -> str:
    session_id = str(uuid.uuid4())
    sessions[session_id] = {
        "id": session_id,
        "created": datetime.datetime.now().isoformat(),
        "cases": [],
        "labels": {},
        "feedback": {},
        "history": {},
    }
    save_session_to_file(session_id)
    return session_id


def get_session(session_id: str) -> dict:
    if session_id in sessions:
        return sessions[session_id]
    loaded = load_session_from_file(session_id)
    if loaded:
        sessions[session_id] = loaded
        return loaded
    return None


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI 测试用例生成器</title>
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono&family=Noto+Sans+SC&display=swap" rel="stylesheet">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: 'Noto Sans SC', sans-serif; background: #f5f5f5; padding: 20px; line-height: 1.6; }
        .container { max-width: 1100px; margin: 0 auto; }
        h1 { text-align: center; margin-bottom: 20px; color: #333; }
        .card { background: white; border-radius: 8px; padding: 20px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        label { display: block; margin-bottom: 5px; font-weight: 500; color: #555; }
        input, textarea, select { width: 100%; padding: 10px; border: 1px solid #ddd; border-radius: 4px; font-size: 14px; font-family: inherit; }
        textarea { font-family: 'JetBrains Mono', monospace; min-height: 100px; resize: vertical; }
        button { background: #4CAF50; color: white; border: none; padding: 12px 24px; border-radius: 4px; cursor: pointer; font-size: 16px; }
        button:hover { background: #45a049; }
        button:disabled { background: #ccc; cursor: not-allowed; }
        .row { display: flex; gap: 10px; margin-bottom: 15px; }
        .row > * { flex: 1; }
        #result { white-space: pre-wrap; }
        .error { color: #d32f2f; background: #ffebee; padding: 10px; border-radius: 4px; }
        .success { color: #388e3c; background: #e8f5e9; padding: 10px; border-radius: 4px; }
        .config-panel { display: none; background: #fff3e0; }
        .config-panel.show { display: block; }
        .btn-secondary { background: #2196F3; }
        .btn-secondary:hover { background: #1976D2; }
        .btn-small { padding: 6px 12px; font-size: 14px; }
        .status { font-size: 12px; color: #666; margin-top: 5px; }
        .case-card { border: 1px solid #eee; border-radius: 6px; padding: 15px; margin-bottom: 15px; }
        .case-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
        .case-id { font-weight: bold; font-size: 16px; color: #333; }
        .case-labels { display: flex; gap: 8px; }
        .label-btn { font-size: 12px; padding: 4px 10px; border-radius: 4px; }
        .label-accepted { background: #e8f5e9; color: #388e3c; }
        .label-rejected { background: #ffebee; color: #d32f2f; }
        .label-needs-fix { background: #fff3e0; color: #f57c00; }
        .case-actions { margin-top: 10px; display: flex; gap: 8px; }
        .feedback-modal { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.5); display: none; justify-content: center; align-items: center; z-index: 1000; }
        .feedback-modal.show { display: flex; }
        .feedback-content { background: white; padding: 25px; border-radius: 8px; width: 500px; max-width: 90%; max-height: 80vh; overflow-y: auto; }
        .batch-actions { background: #e3f2fd; padding: 12px; border-radius: 6px; margin-bottom: 15px; display: flex; gap: 10px; align-items: center; }
        .batch-actions label { display: inline; margin-right: 10px; margin-bottom: 0; }
        .version-badge { font-size: 12px; background: #e3f2fd; color: #1565c0; padding: 2px 8px; border-radius: 4px; display: inline-block; margin-bottom: 10px; }
        .quality-badge { font-size: 12px; background: #fce4ec; color: #c2185b; padding: 2px 8px; border-radius: 4px; display: inline-block; margin-left: 10px; }
        .quality-S { background: #e8f5e9; color: #388e3c; }
        .quality-A { background: #e3f2fd; color: #1565c0; }
        .quality-B { background: #fff3e0; color: #f57c00; }
        .quality-C { background: #ffebee; color: #d32f2f; }
        .quality-D { background: #ffebee; color: #d32f2f; }
    </style>
</head>
<body>
    <div class="container">
        <h1>AI 测试用例生成器</h1>
        <div class="card">
            <label>测试需求描述（文本或上传文件）</label>
            <textarea id="requirement" placeholder="例如：验证用户登录功能，包括正确密码、错误密码、空密码等场景"></textarea>
            <div style="margin-top:10px;">
                <label>或上传需求文件：</label>
                <input type="file" id="reqFile" accept=".csv,.json" style="width:auto;">
                <span id="reqFileName" style="margin-left:10px;color:#666;font-size:12px;"></span>
            </div>
        </div>
        <div class="card">
            <label>示例用例（JSON 数组格式，或上传 CSV / JSON 文件）</label>
            <textarea id="example" placeholder='[{"id": "TC_001", "标题": "正确密码登录", "优先级": "高"}]'></textarea>
            <div style="margin-top:10px;">
                <label>或上传文件：</label>
                <input type="file" id="exampleFile" accept=".csv,.json" style="width:auto;">
                <span id="fileName" style="margin-left:10px;color:#666;font-size:12px;"></span>
            </div>
        </div>
        <div class="card">
            <div class="row">
                <div>
                    <label>生成数量</label>
                    <input type="number" id="count" value="7" min="3" max="20">
                </div>
                <div>
                    <label>启用评审</label>
                    <input type="checkbox" id="reviewMode" style="width:auto;margin-top:25px;">
                </div>
                <div style="display:flex;align-items:flex-end;gap:10px;padding-bottom:10px;">
                    <button onclick="generate()" id="genBtn" style="flex:1;padding:14px;font-size:16px;">生成测试用例</button>
                    <button class="btn-secondary" style="padding:14px;" onclick="toggleConfig()">⚙ 配置</button>
                </div>
                <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:-8px;">
                    <button class="btn-small" style="background:#9c27b0;font-size:12px;" onclick="optimizeAI()">🧠 一键优化</button>
                    <button class="btn-small" style="background:#ff9800;font-size:12px;" onclick="openRuleManager()">📦 规则管理</button>
                </div>
            </div>
        </div>
        <div class="card config-panel" id="configPanel">
            <h4 style="margin-bottom:15px;">基础配置</h4>
            <div class="row">
                <div>
                    <label>Base URL</label>
                    <input type="text" id="cfgBaseUrl" placeholder="https://api.openai.com">
                </div>
                <div>
                    <label>模型名称</label>
                    <input type="text" id="cfgModel" placeholder="gpt-4o-mini">
                </div>
            </div>
            <div class="row">
                <div>
                    <label>API Key</label>
                    <input type="password" id="cfgApiKey" placeholder="留空则使用环境变量">
                </div>
                <div style="display:flex;align-items:flex-end;gap:10px;padding-bottom:10px;">
                    <button class="btn-secondary" onclick="saveConfig()">保存配置</button>
                </div>
            </div>
            <div class="status" id="configStatus"></div>

            <hr style="margin:20px 0;border:0;border-top:1px solid #eee;">

            <h4 style="margin-bottom:15px;">⚡ 高级功能</h4>
            <div style="margin-bottom:15px;padding:12px;background:#fafafa;border-radius:6px;">
                <label style="display:flex;align-items:center;gap:8px;cursor:pointer;">
                    <input type="checkbox" id="expertMode">
                    <div>
                        <strong>三专家模式</strong>
                        <div style="font-size:12px;color:#666;font-weight:normal;">
                            业务专家 + 边界专家 + 攻击专家分别生成，质量更高但耗时约 3 倍
                        </div>
                    </div>
                </label>
            </div>
        </div>
        <div class="card" id="resultCard" style="display:none;">
            <div class="batch-actions">
                <label>批量操作：</label>
                <button class="btn-small btn-secondary" onclick="batchLabel('accepted')">全标 ✅可投产</button>
                <button class="btn-small btn-secondary" onclick="batchLabel('rejected')">全标 ❌舍弃</button>
                <button class="btn-small btn-secondary" onclick="batchLabel('needs_fix')">全标 ⚠️待修改</button>
                <button class="btn-small btn-secondary" onclick="extractRules()">📚 学习规则</button>
                <span style="margin-left: auto; font-size:12px; color:#666;">
                    共 <span id="totalCases">0</span> 条用例
                    <span id="qualityScore"> | 质量评分：<strong>--</strong></span>
                </span>
            </div>
            <div id="result"></div>
            <div style="margin-top:15px;display:flex;gap:10px;">
                <button class="btn-secondary btn-small" onclick="download('markdown')">下载 Markdown</button>
                <button class="btn-secondary btn-small" onclick="download('csv')">下载 CSV</button>
                <button class="btn-small btn-secondary" onclick="downloadSelected()">下载可投产用例</button>
            </div>
        </div>
    </div>

    <div class="feedback-modal" id="feedbackModal">
        <div class="feedback-content">
            <h3 style="margin-bottom:15px;">💬 反馈用例 <span id="feedbackCaseId"></span></h3>
            <label>反馈内容</label>
            <textarea id="feedbackText" style="height:120px; margin-bottom:15px;" placeholder="例如：这个用例的预期结果不对，应该是..."></textarea>
            <div style="display:flex; gap:10px; justify-content:flex-end;">
                <button class="btn-secondary btn-small" onclick="closeFeedbackModal()">取消</button>
                <button onclick="submitFeedback()">提交反馈</button>
            </div>
        </div>
    </div>
    <div class="feedback-modal" id="editModal">
        <div class="feedback-content">
            <h3 style="margin-bottom:15px;">✏️ 编辑用例 <span id="editCaseId"></span></h3>
            <div id="editFields"></div>
            <div style="margin-top:15px;display:flex; gap:10px; justify-content:flex-end;">
                <button class="btn-secondary btn-small" onclick="closeEditModal()">取消</button>
                <button onclick="saveEdit()">保存修改</button>
            </div>
        </div>
    </div>

    <script>
        let lastResult = {};
        let currentSessionId = '';
        let casesWithLabels = [];
        let feedbackTargetCaseId = null;
        let editTargetIndex = null;

        // 页面加载时检查是否有会话需要恢复
        window.addEventListener('DOMContentLoaded', function() {
            const urlParams = new URLSearchParams(window.location.search);
            const sessionId = urlParams.get('session');
            if (sessionId) {
                loadSession(sessionId);
            }
        });

        async function loadSession(sessionId) {
            try {
                const resp = await fetch('/api/session/load', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({session_id: sessionId})
                });
                const result = await resp.json();
                if (result.success && result.session) {
                    currentSessionId = sessionId;
                    casesWithLabels = result.session.cases.map((c, i) => ({
                        ...c,
                        __label: result.session.labels[c.id] || result.session.labels[`TC_${(i+2).toString().padStart(3, '0')}`] || 'unset',
                        __index: i,
                        __history: result.session.history && result.session.history[c.id] ? result.session.history[c.id] : null
                    }));
                    lastResult = {
                        success: true,
                        cases: result.session.cases,
                        session_id: sessionId
                    };
                    document.getElementById('resultCard').style.display = 'block';
                    renderCases();
                    document.getElementById('totalCases').textContent = casesWithLabels.length;
                    history.replaceState(null, '', '?session=' + sessionId);
                }
            } catch (e) {
                console.error('加载会话失败', e);
            }
        }

        document.getElementById('exampleFile').addEventListener('change', async function(e) {
            const file = e.target.files[0];
            if (!file) return;
            document.getElementById('fileName').textContent = '正在解析: ' + file.name;
            const formData = new FormData();
            formData.append('file', file);
            try {
                const resp = await fetch('/api/import', { method: 'POST', body: formData });
                const result = await resp.json();
                if (result.success) {
                    document.getElementById('example').value = JSON.stringify(result.cases, null, 2);
                    document.getElementById('fileName').textContent = '已加载: ' + file.name + ' (' + result.count + ' 条用例)';
                } else {
                    document.getElementById('fileName').textContent = '错误: ' + result.error;
                }
            } catch(err) {
                document.getElementById('fileName').textContent = '错误: ' + err.message;
            }
        });
        document.getElementById('reqFile').addEventListener('change', async function(e) {
            const file = e.target.files[0];
            if (!file) return;
            document.getElementById('reqFileName').textContent = '正在解析: ' + file.name;
            const formData = new FormData();
            formData.append('file', file);
            try {
                const resp = await fetch('/api/import', { method: 'POST', body: formData });
                const result = await resp.json();
                if (result.success) {
                    const text = result.cases.map(c => Object.values(c).join(' ')).join('\\n');
                    document.getElementById('requirement').value = text;
                    document.getElementById('reqFileName').textContent = '已加载: ' + file.name + ' (' + result.count + ' 条)';
                } else {
                    document.getElementById('reqFileName').textContent = '错误: ' + result.error;
                }
            } catch(err) {
                document.getElementById('reqFileName').textContent = '错误: ' + err.message;
            }
        });
        async function generate() {
            const req = document.getElementById('requirement').value.trim();
            const example = document.getElementById('example').value.trim();
            const count = parseInt(document.getElementById('count').value) || 7;
            const reviewMode = document.getElementById('reviewMode').checked;
            const expertMode = document.getElementById('expertMode').checked;
            const resultDiv = document.getElementById('result');
            const resultCard = document.getElementById('resultCard');
            const btn = document.getElementById('genBtn');
            if (!req) return alert('请填写测试需求描述');
            if (!example) return alert('请填写示例用例');
            btn.disabled = true;
            resultDiv.innerHTML = expertMode ? '三专家模式生成中...（业务专家 → 边界专家 → 攻击专家）' : '生成中...';
            resultCard.style.display = 'block';
            try {
                const resp = await fetch('/api/generate', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({requirement: req, example: example, count: count, review_mode: reviewMode, expert_mode: expertMode, session_id: currentSessionId})
                });
                lastResult = await resp.json();
                if (lastResult.success) {
                    if (lastResult.session_id) {
                        currentSessionId = lastResult.session_id;
                        history.pushState(null, '', '?session=' + lastResult.session_id);
                    }
                    casesWithLabels = lastResult.cases.map((c, i) => ({
                        ...c,
                        __label: 'unset',
                        __index: i,
                        __history: lastResult.history && lastResult.history[c.id] ? lastResult.history[c.id] : null
                    }));
                    renderCases();
                    document.getElementById('totalCases').textContent = casesWithLabels.length;
                    // 显示质量评分
                    if (lastResult.quality_score) {
                        const qs = lastResult.quality_score;
                        const levelHtml = `<span class="quality-badge quality-${qs.overall_level}">等级 ${qs.overall_level}</span>`;
                        document.getElementById('qualityScore').innerHTML = ` | 质量评分：<strong>${qs.average_score}</strong>分 ${levelHtml}`;
                    }
                } else {
                    resultDiv.innerHTML = '<div class="error">' + lastResult.error + '</div>';
                }
            } catch(e) {
                resultDiv.innerHTML = '<div class="error">' + e.message + '</div>';
            }
            btn.disabled = false;
        }
        function renderCases() {
            const resultDiv = document.getElementById('result');
            let html = '';
            for (const c of casesWithLabels) {
                const caseId = c.id || `TC_${(c.__index + 2).toString().padStart(3, '0')}`;
                    const hasHistory = c.__history && c.__history.length > 0;
                    const historyBadge = hasHistory ? '<span class="version-badge">✏️ 已编辑</span>' : '';
                let labelHtml = '';
                const labels = [
                    {key: 'accepted', label: '✅可投产', class: 'label-accepted'},
                    {key: 'needs_fix', label: '⚠️待修改', class: 'label-needs-fix'},
                    {key: 'rejected', label: '❌舍弃', class: 'label-rejected'}
                ];
                for (const lbl of labels) {
                    const isActive = c.__label === lbl.key;
                    const activeStyle = isActive ? 'opacity:1; border:1px solid #999;' : 'opacity:0.6;';
                    labelHtml += `<button class="label-btn ${lbl.class}" style="${activeStyle}" onclick="setLabel(${c.__index}, '${lbl.key}')">${lbl.label}</button>`;
                }
                let caseContent = '';
                for (const [k, v] of Object.entries(c)) {
                    if (!k.startsWith('__')) {
                        caseContent += `<div><strong>${k}:</strong> ${v}</div>`;
                    }
                }
                html += `
                    <div class="case-card">
                        <div class="case-header">
                            <span class="case-id">${caseId} ${historyBadge}</span>
                            <div class="case-labels">${labelHtml}</div>
                        </div>
                        <div>${caseContent}</div>
                        <div class="case-actions">
                            <button class="btn-small btn-secondary" onclick="openEditModal('${caseId}', ${c.__index})">✏️ 编辑</button>
                            <button class="btn-small btn-secondary" onclick="openFeedbackModal('${caseId}', ${c.__index})">💬 反馈</button>
                        </div>
                    </div>
                `;
            }
            resultDiv.innerHTML = html;
        }
        function setLabel(index, labelKey) {
            casesWithLabels[index].__label = labelKey;
            renderCases();
            saveLabelsToServer();
        }
        function batchLabel(labelKey) {
            for (const c of casesWithLabels) {
                c.__label = labelKey;
            }
            renderCases();
            saveLabelsToServer();
        }
        async function saveLabelsToServer() {
            if (!currentSessionId) return;
            const labels = {};
            const historyToSave = {};
            for (const c of casesWithLabels) {
                const id = c.id || `TC_${(c.__index + 2).toString().padStart(3, '0')}`;
                labels[id] = c.__label;
                if (c.__history) {
                    historyToSave[id] = c.__history;
                }
            }
            await fetch('/api/session/labels', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({session_id: currentSessionId, labels: labels, history: historyToSave})
            });
        }
        async function extractRules() {
            if (!currentSessionId) return alert('先生成用例或加载会话');
            try {
                const resp = await fetch('/api/extract-rules', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({session_id: currentSessionId})
                });
                const result = await resp.json();
                if (result.success) {
                    const count = result.rules.length;
                    alert(`学习完成！共获得 ${count} 条规则。下次生成会自动应用。`);
                } else {
                    alert('学习失败：' + result.error);
                }
            } catch(e) {
                alert('学习失败：' + e.message);
            }
        }
        function openFeedbackModal(caseId, index) {
            feedbackTargetCaseId = index;
            document.getElementById('feedbackCaseId').textContent = caseId;
            document.getElementById('feedbackText').value = '';
            document.getElementById('feedbackModal').classList.add('show');
        }
        function closeFeedbackModal() {
            document.getElementById('feedbackModal').classList.remove('show');
            feedbackTargetCaseId = null;
        }
        async function submitFeedback() {
            const text = document.getElementById('feedbackText').value.trim();
            if (!text) return alert('请填写反馈内容');
            if (feedbackTargetCaseId === null) return;
            const caseId = casesWithLabels[feedbackTargetCaseId].id || `TC_${(feedbackTargetCaseId + 2).toString().padStart(3, '0')}`;
            closeFeedbackModal();
            await regenerateSingleCase(caseId, feedbackTargetCaseId, text);
        }
        async function regenerateSingleCase(caseId, caseIndex, feedback) {
            const req = document.getElementById('requirement').value.trim();
            const example = document.getElementById('example').value.trim();
            const currentCase = casesWithLabels[caseIndex];
            const btn = document.getElementById('genBtn');
            const resultDiv = document.getElementById('result');
            btn.disabled = true;
            resultDiv.innerHTML = '修改中...';
            try {
                const resp = await fetch('/api/generate-single', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        requirement: req,
                        example: example,
                        session_id: currentSessionId,
                        case_id: caseId,
                        case_index: caseIndex,
                        feedback: feedback,
                        current_case: currentCase
                    })
                });
                const result = await resp.json();
                if (result.success) {
                    casesWithLabels[caseIndex] = {
                        ...result.new_case,
                        __label: casesWithLabels[caseIndex].__label,
                        __index: caseIndex,
                        __history: casesWithLabels[caseIndex].__history || []
                    };
                    if (!casesWithLabels[caseIndex].__history) {
                        casesWithLabels[caseIndex].__history = [];
                    }
                    casesWithLabels[caseIndex].__history.push({
                        timestamp: new Date().toISOString(),
                        feedback: feedback,
                        old_case: currentCase
                    });
                    renderCases();
                    saveLabelsToServer();
                    resultDiv.innerHTML = lastResult.markdown || JSON.stringify(lastResult.cases, null, 2);
                } else {
                    resultDiv.innerHTML = '<div class="error">' + result.error + '</div>';
                }
            } catch(e) {
                resultDiv.innerHTML = '<div class="error">' + e.message + '</div>';
            }
            btn.disabled = false;
        }
        function openEditModal(caseId, index) {
            editTargetIndex = index;
            document.getElementById('editCaseId').textContent = caseId;
            const caseData = casesWithLabels[index];
            let fieldsHtml = '';
            for (const [k, v] of Object.entries(caseData)) {
                if (!k.startsWith('__')) {
                    fieldsHtml += `
                        <label>${k}</label>
                        <textarea data-field="${k}" style="margin-bottom:10px;min-height:60px;">${v || ''}</textarea>
                    `;
                }
            }
            document.getElementById('editFields').innerHTML = fieldsHtml;
            document.getElementById('editModal').classList.add('show');
        }
        function closeEditModal() {
            document.getElementById('editModal').classList.remove('show');
            editTargetIndex = null;
        }
        function saveEdit() {
            if (editTargetIndex === null) return;
            const oldCase = JSON.parse(JSON.stringify(casesWithLabels[editTargetIndex]));
            const fields = document.querySelectorAll('#editFields textarea');
            for (const field of fields) {
                const fieldName = field.getAttribute('data-field');
                casesWithLabels[editTargetIndex][fieldName] = field.value;
            }
            if (!casesWithLabels[editTargetIndex].__history) {
                casesWithLabels[editTargetIndex].__history = [];
            }
            casesWithLabels[editTargetIndex].__history.push({
                timestamp: new Date().toISOString(),
                old: oldCase
            });
            renderCases();
            saveLabelsToServer();
            closeEditModal();
        }
        function toggleConfig() {
            document.getElementById('configPanel').classList.toggle('show');
            if (document.getElementById('configPanel').classList.contains('show')) {
                fetchConfig();
            }
        }
        async function fetchConfig() {
            try {
                const resp = await fetch('/api/config');
                const cfg = await resp.json();
                document.getElementById('cfgBaseUrl').value = cfg.llm.base_url || '';
                document.getElementById('cfgModel').value = cfg.llm.model_name || '';
                document.getElementById('cfgApiKey').value = '';
                document.getElementById('configStatus').textContent =
                    '当前：' + cfg.llm.provider + ' | ' + (cfg.llm.api_key_set ? 'Key 已设置' : 'Key 未设置');
            } catch(e) {}
        }
        async function saveConfig() {
            const base_url = document.getElementById('cfgBaseUrl').value.trim();
            const model_name = document.getElementById('cfgModel').value.trim();
            const api_key = document.getElementById('cfgApiKey').value.trim();
            await fetch('/api/config', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({base_url, model_name, api_key})
            });
            document.getElementById('configStatus').textContent = '配置已保存';
            fetchConfig();
        }
        async function download(type) {
            if (!lastResult.success) return alert('无内容可下载');
            const data = type === 'markdown' ? lastResult.markdown : lastResult.csv;
            if (!data) return alert('无内容');
            const blob = new Blob([data], {type: 'text/plain;charset=utf-8'});
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'test_cases.' + type;
            a.click();
        }
        async function downloadSelected() {
            const selected = casesWithLabels.filter(c => c.__label === 'accepted');
            if (selected.length === 0) return alert('请先将用例标记为"✅可投产"');
            let csv = '';
            const keys = Object.keys(selected[0]).filter(k => !k.startsWith('__'));
            csv += keys.join(',') + '\\n';
            for (const c of selected) {
                const vals = keys.map(k => '"' + String(c[k] || '').replace(/"/g, '""') + '"');
                csv += vals.join(',') + '\\n';
            }
            const blob = new Blob(['\ufeff' + csv], {type: 'text/csv;charset=utf-8'});
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'test_cases_selected.csv';
            a.click();
        }
        async function openRuleManager() {
            const resp = await fetch('/api/rules/export');
            const data = await resp.json();
            const jsonStr = JSON.stringify(data.rules, null, 2);
            
            const html = `
                <div style="margin-bottom:15px;">
                    <h4>📊 规则库统计</h4>
                    <p>总规则数：${data.total_count} | 活跃规则：${data.active_count}</p>
                    <hr style="margin:15px 0;">
                    
                    <h4>📤 导出规则（分享给团队）</h4>
                    <textarea id="exportRulesText" style="height:150px;margin-bottom:10px;font-size:12px;font-family:monospace;">${jsonStr}</textarea>
                    <button class="btn-small btn-secondary" onclick="copyExportedRules()">📋 复制到剪贴板</button>
                    <button class="btn-small btn-secondary" onclick="downloadRules()">💾 下载为文件</button>
                    
                    <hr style="margin:15px 0;">
                    
                    <h4>📥 导入团队规则</h4>
                    <textarea id="importRulesText" style="height:150px;margin-bottom:10px;font-family:monospace;" placeholder="把别人分享的规则 JSON 粘贴到这里"></textarea>
                    <button class="btn-small" style="background:#4caf50;" onclick="importRules()">✅ 导入并合并</button>
                </div>
            `;
            
            const oldContent = document.getElementById('ruleMgrContent');
            if (oldContent) oldContent.remove();
            
            const div = document.createElement('div');
            div.id = 'ruleMgrContent';
            div.innerHTML = html;
            document.querySelector('.container').prepend(div);
        }
        
        async function copyExportedRules() {
            const text = document.getElementById('exportRulesText').value;
            await navigator.clipboard.writeText(text);
            alert('✅ 已复制到剪贴板，直接发给同事就行！');
        }
        
        function downloadRules() {
            const text = document.getElementById('exportRulesText').value;
            const blob = new Blob([text], {type: 'application/json;charset=utf-8'});
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'test-case-rules.json';
            a.click();
        }
        
        async function importRules() {
            const text = document.getElementById('importRulesText').value.trim();
            if (!text) return alert('请先粘贴要导入的规则 JSON');
            
            try {
                const rules = JSON.parse(text);
                const resp = await fetch('/api/rules/import', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({rules})
                });
                const result = await resp.json();
                if (result.success) {
                    alert(`✅ 导入成功！\n\n新增规则：${result.new_rules_added}\n合并已有规则：${result.existing_rules_merged}\n当前总规则数：${result.total_rules_now}`);
                } else {
                    alert('导入失败：' + result.error);
                }
            } catch(e) {
                alert('JSON 解析失败，请检查格式是否正确');
            }
        }

        async function optimizeAI() {
            if (!confirm('确定要运行一键优化吗？\n\n将自动：\n1. 清理低效率规则\n2. 从历史优质用例学习\n3. 更新规则库\n\n此过程需要调用 LLM，可能耗时几十秒。')) return;
            const btn = document.querySelector('button[onclick="optimizeAI()"]');
            const oldText = btn.textContent;
            btn.disabled = true;
            btn.textContent = '优化中...';
            try {
                const resp = await fetch('/api/optimize', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({session_id: currentSessionId})
                });
                const result = await resp.json();
                if (result.success) {
                    alert(`✅ 优化完成！\n\n总规则数：${result.total_rules}\n新学习规则：${result.new_rules}\n淘汰低效率规则：${result.deprecated_rules}`);
                } else {
                    alert('优化失败：' + result.error);
                }
            } catch(e) {
                alert('优化失败：' + e.message);
            }
            btn.disabled = false;
            btn.textContent = oldText;
        }

        window.addEventListener('click', function(e) {
            const feedbackModal = document.getElementById('feedbackModal');
            const editModal = document.getElementById('editModal');
            if (e.target === feedbackModal) closeFeedbackModal();
            if (e.target === editModal) closeEditModal();
        });
    </script>
</body>
</html>"""


class RequestHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def send_json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def send_html(self, html):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def read_json_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length:
            body = self.rfile.read(length).decode("utf-8")
            return json.loads(body)
        return {}

    def parse_multipart(self):
        """解析 multipart/form-data 文件上传"""
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            return None, None

        boundary = content_type.split("boundary=")[-1] if "boundary=" in content_type else None
        if not boundary:
            return None, None

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        part_start = body.find(b"--" + boundary.encode())
        while part_start >= 0:
            part_start = body.find(b"\r\n\r\n", part_start)
            if part_start < 0:
                break
            part_start += 4
            part_end = body.find(b"\r\n--" + boundary.encode(), part_start)
            if part_end < 0:
                part_end = length
            header_part = body[body.find(b"\r\n", body.rfind(b"--" + boundary.encode(), 0, part_start)):part_start-4]
            if b"filename=" in header_part:
                filename_start = header_part.find(b"filename=\"") + 10
                filename_end = header_part.find(b"\"", filename_start)
                filename = header_part[filename_start:filename_end].decode("utf-8", errors="replace")
                file_data = body[part_start:part_end]
                return filename, file_data
            part_start = body.find(b"--" + boundary.encode(), part_end)

        return None, None

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self.send_html(HTML_TEMPLATE)
        elif self.path == "/api/health":
            llm = LLMClient.from_config(config)
            self.send_json(llm.health_check())
        elif self.path == "/api/config":
            llm = config.get("llm", {})
            key = llm.get("api_key") or os.environ.get("LLM_API_KEY", "")
            masked = ("sk-" + "*" * 12 + key[-4:]) if len(key) > 8 else ("*" * len(key) if key else "")
            self.send_json({
                "llm": {
                    "base_url": llm.get("base_url", ""),
                    "model_name": llm.get("model_name", ""),
                    "api_key_set": bool(key),
                    "api_key_masked": masked,
                    "provider": _detect_provider(llm.get("base_url", "")),
                },
                "generation": config.get("generation", {}),
            })
        elif self.path == "/api/history":
            limit = int(self.headers.get("X-History-Limit", "20"))
            offset = int(self.headers.get("X-History-Offset", "0"))
            records = pipeline.get_history(limit, offset)
            self.send_json({"success": True, "records": records})
        else:
            self.send_json({"error": "Not Found"}, 404)

    def do_POST(self):
        if self.path == "/api/import":
            filename, file_data = self.parse_multipart()
            if not filename:
                self.send_json({"success": False, "error": "请上传文件"}, 400)
                return

            suffix = Path(filename).suffix.lower()
            if suffix not in (".csv", ".json"):
                self.send_json({"success": False, "error": f"不支持格式：{suffix}，仅支持 .csv / .json（无第三方依赖）"}, 400)
                return

            import tempfile
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(file_data)
                tmp_path = tmp.name

            try:
                cases = import_file_to_cases(tmp_path)
                os.unlink(tmp_path)
                self.send_json({
                    "success": True,
                    "cases": cases,
                    "count": len(cases),
                })
            except Exception as e:
                try:
                    os.unlink(tmp_path)
                except:
                    pass
                self.send_json({"success": False, "error": str(e)}, 500)
            return

        if self.path == "/api/generate":
            data = self.read_json_body()
            requirement = data.get("requirement", "").strip()
            example = data.get("example", "").strip()
            count = data.get("count", config["generation"]["default_count"])
            review_mode = data.get("review_mode", False)
            session_id = data.get("session_id", "")

            if not requirement:
                self.send_json({"success": False, "error": "请填写测试需求描述"}, 400)
                return
            if not example:
                self.send_json({"success": False, "error": "请填写示例用例"}, 400)
                return
            try:
                count = int(count)
                count = max(config["generation"]["min_count"], min(count, config["generation"]["max_count"]))
            except:
                count = config["generation"]["default_count"]

            expert_mode = data.get("expert_mode", False)
            result = pipeline.run(requirement, example, count, review_mode=review_mode, expert_mode=expert_mode)

            if result.get("success"):
                new_session_id = session_id or new_session()
                if not get_session(new_session_id):
                    new_session_id = new_session()
                session = get_session(new_session_id)
                session["cases"] = result["cases"]
                session["labels"] = {}
                save_session_to_file(new_session_id)
                result["session_id"] = new_session_id

            self.send_json(result)

        elif self.path == "/api/generate-single":
            data = self.read_json_body()
            requirement = data.get("requirement", "").strip()
            example = data.get("example", "").strip()
            session_id = data.get("session_id")
            case_id = data.get("case_id")
            case_index = data.get("case_index")
            feedback = data.get("feedback")
            current_case = data.get("current_case", {})

            if not requirement:
                self.send_json({"success": False, "error": "缺少需求描述"}, 400)
                return
            if not session_id:
                self.send_json({"success": False, "error": "缺少会话ID"}, 400)
                return

            try:
                # 构建单条修改的 prompt
                system_prompt = pipeline._load_system_prompt()
                feedback_prompt = f"""你是专业的测试用例修改专家。请根据用户反馈修改指定的测试用例。

【原始需求】
{requirement}

【原始用例（{case_id}）】
{json.dumps(current_case, ensure_ascii=False)}

【用户反馈】
{feedback}

【要求】
1. 只修改这一条用例，不要修改其他用例
2. 严格按照用户反馈修改
3. 保持其他所有用例完全不变
4. 输出纯 JSON 对象，不要数组！
"""
                raw = pipeline.llm.chat(system_prompt, feedback_prompt)
                
                # 尝试解析返回的对象
                new_case = None
                from src.tools.formatter import FormatValidator
                validator = FormatValidator()
                new_case = validator.extract_json(raw)
                if isinstance(new_case, list) and len(new_case) > 0:
                    new_case = new_case[0]
                elif not isinstance(new_case, dict):
                    try:
                        new_case = json.loads(raw)
                    except:
                        pass

                if new_case and isinstance(new_case, dict):
                    session = get_session(session_id)
                    if session:
                        if "cases" in session and case_index < len(session["cases"]):
                            session["cases"][case_index] = new_case
                            save_session_to_file(session_id)
                    self.send_json({"success": True, "new_case": new_case})
                else:
                    self.send_json({"success": False, "error": "LLM 返回格式有误，请重试"})

            except Exception as e:
                self.send_json({"success": False, "error": str(e)}, 500)

        elif self.path == "/api/session/load":
            data = self.read_json_body()
            session_id = data.get("session_id")
            session = get_session(session_id)
            if session:
                self.send_json({"success": True, "session": session})
            else:
                self.send_json({"success": False, "error": "会话不存在"}, 404)
        elif self.path == "/api/extract-rules":
            data = self.read_json_body()
            session_id = data.get("session_id")
            session = get_session(session_id)
            if not session:
                self.send_json({"success": False, "error": "会话不存在"}, 404)
                return
            
            # 构建反馈文本
            feedback_text = ""
            if session.get("labels"):
                for case_id, label in session["labels"].items():
                    if label == "accepted":
                        feedback_text += f"\n- 用例 {case_id} 标记为 ✅可投产（高质量用例）"
                    elif label == "rejected":
                        feedback_text += f"\n- 用例 {case_id} 标记为 ❌舍弃（低质量用例）"
                    elif label == "needs_fix":
                        feedback_text += f"\n- 用例 {case_id} 标记为 ⚠️待修改（需要改进）"
            
            if not feedback_text:
                self.send_json({"success": True, "rules": memory_store.load_rules()})
                return
            
            try:
                from src.memory.rule_extractor import RuleExtractor
                extractor = RuleExtractor(pipeline.llm)
                new_rules = extractor.extract_from_feedback(feedback_text)
                existing_rules = memory_store.load_rules()
                merged_rules = extractor.merge_rules(existing_rules, new_rules)
                memory_store.save_rules(merged_rules)
                self.send_json({"success": True, "rules": merged_rules})
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}, 500)
            return
        elif self.path == "/api/session/labels":
            data = self.read_json_body()
            session_id = data.get("session_id")
            labels = data.get("labels", {})
            history = data.get("history", {})
            session = get_session(session_id)
            if session:
                session["labels"] = labels
                if "history" not in session:
                    session["history"] = {}
                for case_id, hist in history.items():
                    session["history"][case_id] = hist
                save_session_to_file(session_id)
            self.send_json({"success": True})

        elif self.path == "/api/config":
            data = self.read_json_body()
            llm = config.setdefault("llm", {})
            if "base_url" in data and data["base_url"].strip():
                llm["base_url"] = data["base_url"].strip()
            if "model_name" in data and data["model_name"].strip():
                llm["model_name"] = data["model_name"].strip()
            if "api_key" in data:
                llm["api_key"] = data["api_key"].strip()
            save_config(config)
            rebuild_pipeline()
            self.send_json({"success": True, "message": "配置已更新并持久化"})

        elif self.path == "/api/feedback":
            data = self.read_json_body()
            feedback_file = PROJECT_ROOT / config["storage"]["feedback_file"]
            feedback_file.parent.mkdir(parents=True, exist_ok=True)
            records = []
            if feedback_file.exists():
                try:
                    records = json.loads(feedback_file.read_text(encoding="utf-8"))
                except:
                    records = []
            records.append({
                "timestamp": datetime.datetime.now().isoformat(),
                "rating": data.get("rating"),
                "type": data.get("type", "其他"),
                "comment": data.get("comment", "")[:500],
                "cases_count": data.get("cases_count", 0),
            })
            feedback_file.write_text(json.dumps(records[-500:], ensure_ascii=False, indent=2))
            self.send_json({"success": True})

        elif self.path == "/api/rules/export":
            # 导出所有规则（用于团队共享）
            rules = memory_store.load_rules()
            self.send_json({
                "success": True,
                "rules": rules,
                "export_time": datetime.datetime.now().isoformat(),
                "total_count": len(rules),
                "active_count": len([r for r in rules if not r.get("is_deprecated", False)]),
            })
            return

        elif self.path == "/api/rules/import":
            # 导入团队共享规则（自动去重+合并统计）
            data = self.read_json_body()
            import_rules = data.get("rules", [])
            
            if not import_rules:
                self.send_json({"success": False, "error": "没有要导入的规则"}, 400)
                return

            existing = memory_store.load_rules()
            
            # 合并逻辑：规则文本相同则合并统计，否则新增
            rule_text_map = {r["rule_text"]: r for r in existing}
            new_count = 0
            merged_count = 0
            
            for r in import_rules:
                if "rule_text" not in r:
                    continue
                rule_text = r["rule_text"]
                if rule_text in rule_text_map:
                    # 合并统计
                    existing_rule = rule_text_map[rule_text]
                    existing_rule["use_count"] = existing_rule.get("use_count", 0) + r.get("use_count", 1)
                    existing_rule["effective_count"] = existing_rule.get("effective_count", 0) + r.get("effective_count", 0)
                    merged_count += 1
                else:
                    # 新增规则，保留原统计但重置ID
                    r["rule_id"] = f"RULE_{len(rule_text_map) + new_count + 1:04d}"
                    existing.append(r)
                    new_count += 1
            
            memory_store.save_rules(existing)
            
            self.send_json({
                "success": True,
                "new_rules_added": new_count,
                "existing_rules_merged": merged_count,
                "total_rules_now": len(existing),
            })
            return

        elif self.path == "/api/rules/merge":
            # 合并多个人的规则文件（团队管理员用）
            data = self.read_json_body()
            all_rule_lists = data.get("rule_lists", [])
            
            if len(all_rule_lists) < 2:
                self.send_json({"success": False, "error": "至少需要两份规则才能合并"}, 400)
                return

            # 先把所有规则按文本聚合
            merged_map = {}
            for rule_list in all_rule_lists:
                for r in rule_list:
                    if "rule_text" not in r:
                        continue
                    rt = r["rule_text"]
                    if rt not in merged_map:
                        merged_map[rt] = {
                            "rule_id": "",
                            "rule_text": rt,
                            "type": r.get("type", "general"),
                            "level": r.get("level", "global"),
                            "use_count": 0,
                            "effective_count": 0,
                            "source_count": 0,  # 多少人贡献了这条
                        }
                    # 累加统计
                    merged_map[rt]["use_count"] += r.get("use_count", 1)
                    merged_map[rt]["effective_count"] += r.get("effective_count", 0)
                    merged_map[rt]["source_count"] += 1

            # 重新分配ID
            merged_rules = []
            for i, rule in enumerate(merged_map.values()):
                rule["rule_id"] = f"RULE_{i+1:04d}"
                # 超过3个人都在用的规则，直接标记为优质
                if rule["source_count"] >= 3:
                    rule["level"] = "global"
                merged_rules.append(rule)

            # 按使用量排序
            merged_rules.sort(key=lambda x: -x["use_count"])

            self.send_json({
                "success": True,
                "merged_rules": merged_rules,
                "total_rules": len(merged_rules),
                "high_quality_rules": len([r for r in merged_rules if r["source_count"] >= 3]),
            })
            return

        elif self.path == "/api/optimize":
            # 一键优化：清理低效率规则 + 从优质用例学习
            try:
                from src.memory.rule_manager import RuleManager
                rule_manager = RuleManager(config, PROJECT_ROOT)
                result = rule_manager.optimize_all_rules()
                self.send_json({"success": True, **result})
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}, 500)
            return

        elif self.path == "/api/history/detail":
            data = self.read_json_body()
            record_id = data.get("id", 0)
            detail = pipeline.get_history_detail(record_id)
            if detail:
                self.send_json({"success": True, "record": detail})
            else:
                self.send_json({"success": False, "error": "记录不存在"}, 404)

        elif self.path == "/api/export/markdown":
            data = self.read_json_body()
            content = data.get("markdown", "")
            if not content:
                self.send_json({"error": "无内容"}, 400)
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/markdown; charset=utf-8")
            self.send_header("Content-Disposition", "attachment; filename=test_cases.md")
            self.end_headers()
            self.wfile.write(content.encode("utf-8"))

        elif self.path == "/api/export/csv":
            data = self.read_json_body()
            content = data.get("csv", "")
            if not content:
                self.send_json({"error": "无内容"}, 400)
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", "attachment; filename=test_cases.csv")
            self.end_headers()
            self.wfile.write(content.encode("utf-8-sig"))

        else:
            self.send_json({"error": "Not Found"}, 404)


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    host = os.environ.get("HOST", "0.0.0.0")

    llm_cfg = config.get("llm", {})
    key_status = "已设置" if (llm_cfg.get("api_key") or os.environ.get("LLM_API_KEY")) else "未设置（内网无鉴权模式）"

    print("╔══════════════════════════════════════════════════╗")
    print("║        AI 测试用例生成器 — 启动中                ║")
    print("╠══════════════════════════════════════════════════╣")
    print(f"║  访问地址：http://localhost:{port}                 ║")
    print(f"║  LLM 地址：{llm_cfg.get('base_url','')[:36]:<36} ║")
    print(f"║  模型名称：{llm_cfg.get('model_name','')[:36]:<36} ║")
    print(f"║  API Key ：{key_status:<36} ║")
    print("╚══════════════════════════════════════════════════╝")
    print("  提示：使用纯 Python 标准库，无第三方依赖")
    print("  P2 第二阶段：用例标签、批量操作已启用")

    server = ThreadedHTTPServer((host, port), RequestHandler)
    server.serve_forever()
