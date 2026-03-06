# QUICKSTART â€” 10 åˆ†é’Ÿä¸Šæ‰‹ gcc-evo v5.305

---

## å®‰è£…ï¼ˆ2 åˆ†é’Ÿï¼‰

```bash
# å…‹éš†æˆ–ä¸‹è½½æºç 
git clone https://github.com/baodexiang/gcc-evo.git
cd gcc-evo

# å®‰è£…ä¾èµ–
pip install -e .

# éªŒè¯å®‰è£…
gcc-evo version
# è¾“å‡º: gcc-evo v5.305
```

---

## é…ç½®ï¼ˆ2 åˆ†é’Ÿï¼‰

ç¼–è¾‘ `evolution.yaml`ï¼ˆæˆ–æ–°å»ºï¼‰ï¼Œé…ç½® LLM APIï¼š

```yaml
# evolution.yaml
llm_providers:
  gemini:
    api_key: ${GCC_GEMINI_KEY}    # ä»ŽçŽ¯å¢ƒå˜é‡è¯»å–
    model: gemini-2.0-pro

  openai:
    api_key: ${GCC_OPENAI_KEY}
    model: gpt-4-turbo

  claude:
    api_key: ${GCC_CLAUDE_KEY}
    model: claude-opus-4

default_provider: claude
```

è®¾ç½®çŽ¯å¢ƒå˜é‡ï¼š
```bash
export GCC_CLAUDE_KEY=sk-ant-...
export GCC_GEMINI_KEY=AIza...
export GCC_OPENAI_KEY=sk-proj-...
```

æˆ–å¤åˆ¶ `evolution.example.yaml`ï¼š
```bash
cp evolution.example.yaml evolution.yaml
# ç¼–è¾‘ evolution.yamlï¼Œå¡«å…¥ä½ çš„ API Key
```

---

## åˆå§‹åŒ–é¡¹ç›®ï¼ˆ1 åˆ†é’Ÿï¼‰

```bash
# åˆ›å»º .GCC/ ç›®å½•å’Œå¿…è¦æ–‡ä»¶
gcc-evo init

# æ–‡ä»¶ç»“æž„
.GCC/
â”œâ”€â”€ gcc.db              # æ”¹å–„åŽ†å²æ•°æ®åº“
â”œâ”€â”€ pipeline/
â”‚   â””â”€â”€ tasks.json      # ä»»åŠ¡ç®¡é“
â”œâ”€â”€ state/
â”‚   â””â”€â”€ improvements.json  # KEY/æ”¹å–„é¡¹å®šä¹‰
â””â”€â”€ handoff/            # äº¤æŽ¥æ–‡æ¡£
```

---

## L0 é¢„å…ˆè®¾ç½®ï¼ˆæ–°ï¼å¿…é¡»å…ˆåšï¼‰

v5.305 æ–°å¢žï¼šæ¯æ¬¡ loop å‰å¿…é¡»å…ˆå®Œæˆ L0 é…ç½®ã€‚

```bash
# é¦–æ¬¡é…ç½®ï¼ˆäº¤äº’å¼å‘å¯¼ï¼‰
gcc-evo setup KEY-010

# å‘å¯¼ä¼šä¾æ¬¡è¯¢é—®ï¼š
#   KEYç¼–å·:       KEY-010
#   è¿›åŒ–ç›®æ ‡:      æå‡ä¿¡å·å‡†ç¡®çŽ‡ï¼ˆè‡³å°‘10å­—ï¼‰
#   æˆåŠŸæ ‡å‡†:      1. ä¿¡å·å‡†ç¡®çŽ‡>80%
#                  2. è¯¯æŠ¥çŽ‡<10%
#   äººå·¥ç¡®è®¤:      Y/nï¼ˆæ¯è½®ç»“æŸæ˜¯å¦æš‚åœç­‰å¾…ç¡®è®¤ï¼‰
#   æœ€å¤§å¾ªçŽ¯æ¬¡æ•°:  0=ä¸é™
#   å¤‡æ³¨:          ï¼ˆå¯é€‰ï¼‰

# æŸ¥çœ‹å½“å‰é…ç½®
gcc-evo setup --show

# ç¼–è¾‘æŸä¸ªå­—æ®µ
gcc-evo setup --edit

# é‡ç½®é…ç½®ï¼ˆé‡æ–°å¡«å†™ï¼‰
gcc-evo setup --reset
```

é…ç½®å­˜å‚¨åœ¨ `.GCC/state/session_config.json`ã€‚

---

## æ ¸å¿ƒå·¥ä½œæµï¼ˆ5 åˆ†é’Ÿï¼‰

### 1. å®šä¹‰æ”¹å–„æ–¹å‘ï¼ˆKEYï¼‰

```bash
# å…ˆå®Œæˆ L0 KEY é…ç½®
gcc-evo setup KEY-001
```

è¾“å‡ºç¤ºä¾‹ï¼š
```
KEY-001: æé«˜äº¤æ˜“ä¿¡å·å‡†ç¡®çŽ‡
KEY-002: é™ä½Žè™šå‡ä¿¡å·
...
```

### 2. åˆ›å»ºä»»åŠ¡

```bash
# ä¸º KEY-001 åˆ›å»ºä»»åŠ¡
gcc-evo pipe task "æ”¹å–„ä¿¡å·å‡†ç¡®çŽ‡ Phase 1" -k KEY-001 -m core -p P1
```

### 3. è¿è¡Œ Loop é—­çŽ¯

```bash
# å‰æï¼šå…ˆå®Œæˆ L0 é…ç½®ï¼ˆgcc-evo setup KEY-010ï¼‰

# å•æ¬¡é—­çŽ¯ï¼ˆåˆ†æžâ†’è’¸é¦â†’æ›´æ–°ï¼‰
gcc-evo loop GCC-0001 --once

# æŒç»­é—­çŽ¯ï¼ˆæ¯ 5 åˆ†é’Ÿè‡ªåŠ¨è¿è¡Œï¼‰
gcc-evo loop GCC-0001

# æµ‹è¯•ç”¨ï¼šè·³è¿‡ L0 gate
gcc-evo loop GCC-0001 --once --dry-run
```

Loop ä¼šè‡ªåŠ¨æ‰§è¡Œï¼š
1. **Tasks** â€” è¯»å–ä»»åŠ¡è¿›åº¦
2. **Audit** â€” åˆ†æžæ—¥å¿—ï¼Œå‘çŽ°é—®é¢˜
3. **Cards** â€” ç”Ÿæˆç»éªŒå¡
4. **Rules** â€” æå–å¯å¤ç”¨è§„åˆ™
5. **Distill** â€” è’¸é¦åˆ° SkillBank
6. **Report** â€” æ˜¾ç¤ºé—­çŽ¯æ‘˜è¦

ç¤ºä¾‹è¾“å‡ºï¼š
```
ðŸ”„ Loop Cycle: GCC-0001
â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
âœ“ Step 1: Tasks [2/5 done]
âœ“ Step 2: Audit [5 issues found]
  - Issue-1: ä¿¡å·å»¶è¿Ÿ 100ms
  - Issue-2: è™šå‡çªç ´è§¦å‘çŽ‡ 12%
âœ“ Step 3: Cards [æ–°å¢ž 3 å¼ ç»éªŒå¡]
âœ“ Step 4: Rules [æå– 5 æ¡è§„åˆ™]
âœ“ Step 5: Distill [SkillBank +2 æŠ€èƒ½]
âœ“ Step 6: Report [é¢„è®¡æ”¹å–„: +3% å‡†ç¡®çŽ‡]

Status: HEALTHY
Next Iteration: 5 minutes
```

### 4. æŸ¥çœ‹è¿›åº¦

```bash
# å¥åº·æ£€æŸ¥
gcc-evo health

# æŸ¥çœ‹å½“å‰ L0 é…ç½®
gcc-evo setup --show

# æŸ¥çœ‹ä»»åŠ¡è¯¦æƒ…
gcc-evo pipe status GCC-0001
```

---

## å¸¸ç”¨å‘½ä»¤é€ŸæŸ¥

| å‘½ä»¤ | è¯´æ˜Ž |
|------|------|
| `gcc-evo setup KEY-010` | L0 é…ç½®å‘å¯¼ï¼ˆå¿…é¡»å…ˆåšï¼‰ |
| `gcc-evo setup --show` | æŸ¥çœ‹å½“å‰ L0 é…ç½® |
| `gcc-evo setup --edit` | ç¼–è¾‘ L0 é…ç½®å­—æ®µ |
| `gcc-evo init` | åˆå§‹åŒ–é¡¹ç›®ç»“æž„ |
| `gcc-evo loop GCC-001 --once` | å•æ¬¡é—­çŽ¯ |
| `gcc-evo loop GCC-001 --dry-run` | è·³è¿‡ L0 gate æµ‹è¯• |
| `gcc-evo pipe task "æ ‡é¢˜" -k KEY-001 -m core -p P1` | åˆ›å»ºä»»åŠ¡ |
| `gcc-evo pipe list` | åˆ—å‡ºæ‰€æœ‰ä»»åŠ¡ |
| `gcc-evo memory compact` | åŽ‹å®žé•¿æœŸè®°å¿† |
| `gcc-evo health` | ç³»ç»Ÿå¥åº·æ£€æŸ¥ |

---

## åˆ‡æ¢ LLM æ¨¡åž‹

gcc-evo æ”¯æŒæ— ç¼åˆ‡æ¢æ¨¡åž‹ï¼Œæ— æŸä¸Šä¸‹æ–‡ï¼š

```bash
# ç”¨ Gemini è·‘æœ¬æ¬¡ loop
gcc-evo loop GCC-0001 --provider gemini --once

# ç”¨ OpenAI è·‘ä¸€æ¬¡ loop
gcc-evo loop GCC-0001 --provider openai --once

# å¤šæ¨¡åž‹åä½œï¼ˆSkeptic éªŒè¯ï¼‰
# é»˜è®¤ç”¨ claude å†³ç­–ï¼Œgemini + openai éªŒè¯
gcc-evo loop GCC-0001 --once
```

---

## æ•…éšœæŽ’æŸ¥

### é—®é¢˜ 1ï¼šAPI Key æ‰¾ä¸åˆ°

```
Error: GCC_CLAUDE_KEY not set
```

**è§£å†³**ï¼š
```bash
export GCC_CLAUDE_KEY=ä½ çš„key
# æˆ–ç¼–è¾‘ evolution.yamlï¼Œç›´æŽ¥å¡«å…¥ key
```

### é—®é¢˜ 2ï¼šæƒé™ä¸è¶³

```
PermissionError: [Errno 13] Permission denied: '.GCC/gcc.db'
```

**è§£å†³**ï¼š
```bash
chmod +x .GCC
chmod 644 .GCC/gcc.db
```

### é—®é¢˜ 3ï¼šLoop å¡ä½

```bash
# æŸ¥çœ‹æ—¥å¿—
tail -f .GCC/logs/loop.log

# å¼ºåˆ¶ä¸­æ­¢
Ctrl+C

# é‡æ–°åˆå§‹åŒ–é¡¹ç›®ç»“æž„
gcc-evo init
```

---

## ä¸‹ä¸€æ­¥

- ðŸ‘‰ å®Œæ•´æ–‡æ¡£ï¼š[README.md](README.md)
- ðŸ”’ å®‰å…¨æ”¿ç­–ï¼š[SECURITY.md](SECURITY.md)
- ðŸ¤ è´¡çŒ®æŒ‡å—ï¼š[CONTRIBUTING.md](CONTRIBUTING.md)
- ðŸ“š é«˜çº§ç”¨æ³•ï¼š`gcc-evo <command> --help`

---

**ç¥ä½ ç”¨å¾—æ„‰å¿«ï¼**

æœ‰é—®é¢˜ï¼Ÿ[æäº¤ Issue](https://github.com/baodexiang/gcc-evo/issues)


