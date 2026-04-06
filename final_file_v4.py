#!/usr/bin/env python3
"""
universal_dead_code_scanner.py  v3.0
False-positive reduction for ALL languages:
  1. Skip vendored/third-party dirs
  2. Confidence scoring HIGH / MED / LOW
  3. Per-language framework-callback blocklists
  4. Cross-reference against build/config files
  5. LOW results hidden by default (--show-low to reveal)
"""
import subprocess,tempfile,shutil,json,sys,os,re
from pathlib import Path
from collections import defaultdict

R="\033[91m";Y="\033[93m";G="\033[92m";C="\033[96m"
B="\033[94m";M="\033[95m";BO="\033[1m";DM="\033[2m";RS="\033[0m"

def clr(t,*c):return "".join(c)+str(t)+RS
def hdr(title,col=C):pass
def row(label,reason,conf,col=Y,indent=4):pass
def run(cmd,cwd=None,timeout=180):
    return subprocess.run(cmd,cwd=cwd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=timeout)

VENDOR_DIRS={
    'vendor','third_party','third-party','thirdparty','external','extern',
    'deps','dependencies','lib','libs','submodules','submodule',
    'node_modules','venv','.venv','env','.env','site-packages','__pycache__',
    'eggs','.eggs','dist-info','egg-info','dist','build','out','target','_build',
    '.next','.nuxt','.cache','coverage','htmlcov','.tox','.git','.idea','.vscode',
    '.github','prebuilt','precompiled','generated','gen','proto',
    'cocos','cocos2d','cocos2dx','SDL','freetype','libpng','libjpeg',
    'tinyxml','tinyxml2','zlib','minizip','curl','openssl','ffmpeg',
    'webp','libwebp',
}
BUILD_EXTS={'.cmake','.mk','.gradle','.bazel','.toml','.yaml','.yml',
            '.json','.xml','.ini','.cfg','.conf','.ld','.map','.def','.exp','.sym'}
BUILD_NAMES={'CMakeLists.txt','Makefile','makefile','BUILD','BUCK'}

def is_vendored(path,root):
    rel=Path(os.path.relpath(path,root))
    return any(p.lower() in VENDOR_DIRS for p in rel.parts)

def collect_build_corpus(root):
    parts=[]
    for path in Path(root).rglob('*'):
        if is_vendored(path,root):continue
        if path.name in BUILD_NAMES or path.suffix.lower() in BUILD_EXTS:
            try:parts.append(path.read_text(errors='replace'))
            except:pass
    return '\n'.join(parts)

def all_files(root,extensions):
    result=[]
    for path in Path(root).rglob('*'):
        if is_vendored(path,root):continue
        if path.suffix.lower() in extensions:result.append(path)
    return result

def all_source_text(root,extensions):
    parts=[]
    for path in Path(root).rglob('*'):
        if is_vendored(path,root):continue
        if path.suffix.lower() in extensions:
            try:parts.append(path.read_text(errors='replace'))
            except:pass
    return '\n'.join(parts)

OS_ENTRIES={'DllMain','WinMain','wWinMain','wmain','main','init','setup',
            'JNI_OnLoad','JNI_OnUnload','_start','__start'}
CB_PATS=[r'^on[A-Z]',r'^handle[A-Z_]',r'^do[A-Z]',r'[Cc]allback',
         r'[Hh]andler',r'[Ll]istener',r'Impl$',r'Override$']
FP_C_PATS=[r'^Java_',r'^Py[A-Z]',r'^WebP',r'^cc[A-Z0-9]',r'^hsv_',
           r'^CF[A-Z]',r'^gl[A-Z]',r'^vk[A-Z]',r'_hook$',r'_cb$',
           r'_callback$',r'_handler$',r'_impl$',r'_internal$']

def score(sym,in_build,is_header,extra_penalty=0):
    s=3
    if in_build:s-=2
    if is_header:s-=1
    if sym in OS_ENTRIES:s-=2
    if sym.startswith('Java_'):s-=3
    if sym.startswith('__'):s-=1
    if any(re.search(p,sym) for p in CB_PATS):s-=1
    s-=extra_penalty
    return max(1,min(3,s))

EXT_MAP={'.js':'js','.jsx':'js','.ts':'js','.tsx':'js','.mjs':'js','.cjs':'js',
         '.py':'python','.go':'go','.rb':'ruby','.java':'java','.kt':'java',
         '.css':'css','.scss':'css','.sass':'css','.less':'css',
         '.rs':'rust','.php':'php',
         '.c':'c','.cpp':'c','.cc':'c','.cxx':'c','.h':'c','.hpp':'c'}

def detect_languages(root):
    counts=defaultdict(int)
    for path in Path(root).rglob('*'):
        if is_vendored(path,root):continue
        lang=EXT_MAP.get(path.suffix.lower())
        if lang:counts[lang]+=1
    return counts

# ── JS/TS (knip — AST, always HIGH) ──────────────────────────────────────────
def scan_js(root,_bc):
    results=[]
    if not (Path(root)/'package.json').exists():return results
    run(['npm','install','--ignore-scripts','--prefer-offline'],cwd=root)
    r=run(['npx','--yes','knip','--reporter','json'],cwd=root)
    try:data=json.loads(r.stdout.strip())
    except:return results
    for issue in data.get('issues',[]):
        f=issue.get('file','')
        if any(v in f for v in ['node_modules','/vendor/','/third_party/']):continue
        if issue.get('files'):
            results.append({'type':'unused_file','file':f,'confidence':3,'reason':_js_fr(f)})
        for dep in issue.get('dependencies',[])+issue.get('devDependencies',[]):
            name=dep.get('name',dep) if isinstance(dep,dict) else dep
            results.append({'type':'unused_dep','file':'package.json','symbol':name,'confidence':3,'reason':_js_dr(name)})
        for exp in issue.get('exports',[]):
            sym=exp.get('name',exp) if isinstance(exp,dict) else exp
            results.append({'type':'unused_export','file':f,'symbol':sym,'confidence':2,'reason':'Exported but never imported by any other module'})
        for u in issue.get('unlisted',[]):
            sym=u.get('name',u) if isinstance(u,dict) else u
            results.append({'type':'missing_dep','file':f,'symbol':sym,'confidence':3,'reason':'Used in code but missing from package.json'})
    return results

def _js_fr(f):
    if 'components/ui/' in f:return 'shadcn/ui component installed but never imported'
    if '.test.' in f or '.spec.' in f:return 'Test/spec file not reachable via entry point'
    if 'config' in f:return 'Config file never imported (may be auto-loaded)'
    return 'Never imported or referenced anywhere in the codebase'

def _js_dr(n):
    if '@radix-ui/' in n:return 'Radix UI primitive — shadcn component installed but unused'
    if 'eslint' in n:return 'ESLint plugin not referenced in any ESLint config'
    if 'babel' in n:return 'Babel plugin not in active babel config'
    if 'jest' in n or 'testing' in n:return 'Test utility unreachable by knip'
    if 'webpack' in n or 'loader' in n:return 'Webpack plugin/loader not in active webpack config'
    return 'Listed in package.json but never imported in code'

# ── Python (vulture) ──────────────────────────────────────────────────────────
PY_HOOKS={'get_queryset','get_context_data','form_valid','form_invalid','dispatch',
          'get','post','put','patch','delete','save','clean','ready','handle',
          'before_request','after_request','run','on_failure','on_success',
          'setUp','tearDown','setup_method','teardown_method','setup_class','teardown_class',
          '__init__','__str__','__repr__','__len__','__iter__','__next__',
          '__enter__','__exit__','__call__','__getitem__','__setitem__',
          '__contains__','__eq__','__hash__','__lt__','__le__','__gt__','__ge__',
          '__add__','__sub__','__mul__','__truediv__','__mod__','__pow__',
          '__bool__','__int__','__float__','__bytes__','__del__','__new__'}

def scan_python(root,bc):
    results=[]
    py_files=all_files(root,{'.py'})
    if not py_files:return results
    try:
        r=run(['python3','-m','vulture',str(root),'--min-confidence','70',
               '--exclude','*venv*,*__pycache__*,*/dist/*,*/build/*,*.eggs*,*/vendor/*,*/third_party/*'],
              timeout=90)
    except Exception as e:
        pass
    pat=re.compile(r'^(.+):(\d+):\s+(.+?)\'(.+?)\'\s+\((\d+)%\s+confidence\)')
    for line in r.stdout.splitlines():
        m=pat.match(line)
        if not m:continue
        fp,ln,kind,name,conf=m.groups()
        if is_vendored(Path(fp),root):continue
        is_hook=name in PY_HOOKS or name.startswith('__')
        in_bc=bool(re.search(r'\b'+re.escape(name)+r'\b',bc))
        if is_hook:c=1
        elif in_bc:c=1
        elif int(conf)>=90:c=3
        elif int(conf)>=80:c=2
        else:c=1
        rel=os.path.relpath(fp,root)
        results.append({'type':'python_dead','file':rel,'line':int(ln),'symbol':name,
                        'confidence':c,'reason':_py_reason(kind.strip(),name,is_hook)})
    return results

def _py_reason(kind,name,hook):
    if hook:return 'Framework/dunder method — called by the framework, not directly'
    if 'function' in kind:
        if name.startswith('test_'):return 'Test function — verify pytest discovers it'
        if name.startswith('_'):return 'Private function never called in this package'
        return 'Function defined but never called anywhere'
    if 'method' in kind:return 'Method defined but never called on any instance'
    if 'class' in kind:return 'Class never instantiated or subclassed'
    if 'variable' in kind or 'attribute' in kind:
        if name.isupper():return 'Constant never referenced — safe to remove'
        return 'Variable/attribute assigned but never read'
    if 'import' in kind:return 'Import never used in this file'
    return 'Unused code (vulture)'

# ── Go ────────────────────────────────────────────────────────────────────────
GO_SKIP={'main','init','String','Error','MarshalJSON','UnmarshalJSON','MarshalText',
         'UnmarshalText','ServeHTTP','Handle','Run','Start','Stop','Close','Open',
         'New','Reset','Write','Read','Flush','Len','Less','Swap','Sort','Scan',
         'Format','Unwrap','Is','As','RoundTrip'}

def scan_go(root,bc):
    results=[]
    go_files=all_files(root,{'.go'})
    if not go_files:return results
    defined,all_lines=[],[]
    for fpath in go_files:
        try:lines=fpath.read_text(errors='replace').splitlines()
        except:continue
        rel=os.path.relpath(fpath,root)
        def_set=set()
        for i,line in enumerate(lines,1):
            m=re.match(r'^func\s+(?:\([^)]+\)\s+)?(\w+)\s*[\(\[]',line)
            if m:defined.append((m.group(1),rel,i));def_set.add(i)
        for i,line in enumerate(lines,1):all_lines.append((rel,i,line,i in def_set))
    called=set()
    for _,_,line,is_def in all_lines:
        if not is_def:called|=set(re.findall(r'\b(\w+)\s*\(',line))
    for fn,fpath,lineno in defined:
        if fn in GO_SKIP:continue
        if fn.startswith('Test') or fn.startswith('Benchmark') or fn.startswith('Example'):continue
        if fn not in called:
            in_bc=bool(re.search(r'\b'+re.escape(fn)+r'\b',bc))
            c=score(fn,in_bc,False)
            results.append({'type':'go_dead_func','file':fpath,'line':lineno,'symbol':fn,
                            'confidence':c,'reason':_go_reason(fn)})
    for fpath in go_files:
        try:content=fpath.read_text(errors='replace')
        except:continue
        rel=os.path.relpath(fpath,root)
        blocks=re.findall(r'import\s*\(([^)]+)\)',content)
        singles=re.findall(r'import\s+"([^"]+)"',content)
        imports=re.findall(r'"([^"]+)"','\n'.join(blocks))+singles
        clean=re.sub(r'import\s*\(.*?\)','',content,flags=re.DOTALL)
        clean=re.sub(r'import\s+"[^"]+"','',clean)
        for imp in imports:
            alias=imp.split('/')[-1]
            if not re.search(r'\b'+re.escape(alias)+r'\b',clean):
                results.append({'type':'go_unused_import','file':rel,'symbol':imp,'confidence':3,
                                'reason':f'Import "{imp}" declared but alias never used'})
    return results

def _go_reason(fn):
    if fn[0].islower():return 'Unexported function — only visible within package, never called'
    return 'Exported function — never called in this repo (may be a public API)'

# ── Ruby ──────────────────────────────────────────────────────────────────────
RB_SKIP={'initialize','to_s','to_str','to_a','to_h','to_i','to_f','inspect',
         'call','perform','execute','run','up','down','change',
         'each','map','select','reject','find','all','any','count'}

def scan_ruby(root,bc):
    results=[]
    rb_files=all_files(root,{'.rb'})
    if not rb_files:return results
    all_defined,all_words=[],set()
    for fpath in rb_files:
        try:lines=fpath.read_text(errors='replace').splitlines()
        except:continue
        rel=os.path.relpath(fpath,root)
        def_lines=set()
        for i,line in enumerate(lines,1):
            m=re.match(r'^\s*def\s+(self\.)?(\w+[!?]?)',line)
            if m:all_defined.append((m.group(2),rel,i));def_lines.add(i)
        for i,line in enumerate(lines,1):
            if i not in def_lines:all_words|=set(re.findall(r'\b(\w+)\b',line))
    for fn,fpath,lineno in all_defined:
        if fn in RB_SKIP or fn.startswith('test_'):continue
        base=fn.rstrip('!?')
        if base not in all_words and fn not in all_words:
            in_bc=bool(re.search(r'\b'+re.escape(fn)+r'\b',bc))
            c=score(fn,in_bc,False)
            results.append({'type':'ruby_dead','file':fpath,'line':lineno,'symbol':fn,
                            'confidence':c,'reason':_rb_reason(fn)})
    return results

def _rb_reason(fn):
    if fn.startswith('_'):return 'Private-style method never called'
    if fn.endswith('?'):return 'Predicate method defined but never called'
    if fn.endswith('!'):return 'Bang method defined but never called'
    return 'Method never referenced in any .rb file'

# ── Java / Kotlin ─────────────────────────────────────────────────────────────
JAVA_SKIP={'main','toString','equals','hashCode','compareTo','iterator','clone',
           'onCreate','onStart','onResume','onPause','onStop','onDestroy','onRestart',
           'onCreateView','onDestroyView','onViewCreated','onActivityCreated',
           'onAttach','onDetach','onSurfaceCreated','onSurfaceChanged','onDrawFrame',
           'onTouchEvent','onKeyDown','onKeyUp','onMeasure','onLayout','onDraw',
           'onSizeChanged','onAccuracyChanged','onSensorChanged','onLoadComplete',
           'handleMessage','onClick','onTextChanged','onEditorAction',
           'run','execute','call','build','apply','init','close','open','flush',
           'configure','setUp','tearDown','before','after','doGet','doPost','service',
           'handle','process','filter','invoke','finalize'}

def scan_java(root,bc):
    results=[]
    java_files=all_files(root,{'.java','.kt'})
    if not java_files:return results
    all_defined,all_words=[],set()
    for fpath in java_files:
        try:lines=fpath.read_text(errors='replace').splitlines()
        except:continue
        rel=os.path.relpath(fpath,root)
        def_lines=set()
        for i,line in enumerate(lines,1):
            m=re.search(r'(?:private|protected|public|static|final|\s)+\s+[\w<>\[\]]+\s+(\w+)\s*\(',line)
            if m and not re.search(r'\bclass\b|\binterface\b|\benum\b|\@',line):
                all_defined.append((m.group(1),rel,i));def_lines.add(i)
            mk=re.match(r'^\s*(?:(?:private|protected|internal|override|suspend|open|abstract|inline)\s+)*fun\s+(\w+)',line)
            if mk:all_defined.append((mk.group(1),rel,i));def_lines.add(i)
        for i,line in enumerate(lines,1):
            if i not in def_lines:all_words|=set(re.findall(r'\b(\w+)\b',line))
    for fn,fpath,lineno in all_defined:
        if fn in JAVA_SKIP:continue
        if fn.startswith(('get','set','test','on','is','has','do','can','will','did','was')):continue
        if fn not in all_words:
            in_bc=bool(re.search(r'\b'+re.escape(fn)+r'\b',bc))
            c=score(fn,in_bc,fpath.endswith('.kt'))
            results.append({'type':'java_dead','file':fpath,'line':lineno,'symbol':fn,
                            'confidence':c,'reason':_java_reason(fn)})
    return results

def _java_reason(fn):
    if fn[0].islower():return 'Package/private method — defined but never called'
    return 'Public method — never called (may be a public API — verify)'

# ── CSS / SCSS ────────────────────────────────────────────────────────────────
def scan_css(root,_bc):
    results=[]
    css_files=all_files(root,{'.css','.scss','.sass','.less'})
    html_files=all_files(root,{'.html','.htm','.jsx','.tsx','.js','.ts',
                                '.vue','.svelte','.erb','.haml','.jinja','.j2','.py','.rb','.php'})
    if not css_files:return results
    used_cls,used_ids=set(),set()
    for fpath in html_files:
        try:content=fpath.read_text(errors='replace')
        except:continue
        for m in re.finditer(r'class(?:Name)?\s*[=:]\s*["\']([^"\']+)["\']',content):
            used_cls|=set(m.group(1).split())
        used_cls|=set(re.findall(r'["\'\`]([a-zA-Z][\w-]{1,40})["\'\`]',content))
        used_cls|=set(re.findall(r'\b([a-zA-Z][\w-]{2,30})\b',content))
        for m in re.finditer(r'id\s*=\s*["\']([^"\']+)["\']',content):
            used_ids.add(m.group(1))
    SKIP_PFX=('is-','has-','js-','was-','will-','no-','not-','sm-','md-','lg-',
               'xl-','hover-','focus-','active-','disabled-','dark-','light-')
    for fpath in css_files:
        try:content=fpath.read_text(errors='replace')
        except:continue
        rel=os.path.relpath(fpath,root)
        clean=re.sub(r'/\*.*?\*/','',content,flags=re.DOTALL)
        clean=re.sub(r'//.*$','',clean,flags=re.MULTILINE)
        for i,line in enumerate(clean.splitlines(),1):
            for m in re.finditer(r'\.([a-zA-Z][\w-]*)\s*[\{,:\[]',line):
                cls=m.group(1)
                if cls.startswith(SKIP_PFX):continue
                if cls not in used_cls:
                    results.append({'type':'css_dead_class','file':rel,'line':i,'symbol':f'.{cls}',
                                    'confidence':2,'reason':f'Class ".{cls}" not found in any template/JS'})
            for m in re.finditer(r'#([a-zA-Z][\w-]*)\s*[\{,:\[]',line):
                id_=m.group(1)
                if id_ not in used_ids:
                    results.append({'type':'css_dead_id','file':rel,'line':i,'symbol':f'#{id_}',
                                    'confidence':2,'reason':f'ID "#{id_}" not used in any template'})
    return results

# ── Rust ──────────────────────────────────────────────────────────────────────
RUST_SKIP={'main','new','default','fmt','from','into','clone','drop','eq','hash',
           'next','poll','run','start','stop','close','open','read','write','flush',
           'seek','len','is_empty','iter','serialize','deserialize','deref',
           'deref_mut','index','add','sub','mul','div','rem','neg','display','debug'}

def scan_rust(root,bc):
    results=[]
    rs_files=all_files(root,{'.rs'})
    if not rs_files:return results
    all_defined,all_words=[],set()
    for fpath in rs_files:
        try:lines=fpath.read_text(errors='replace').splitlines()
        except:continue
        rel=os.path.relpath(fpath,root)
        def_lines=set()
        for i,line in enumerate(lines,1):
            prev=lines[i-2] if i>1 else ''
            if re.search(r'#\[(?:test|allow\s*\(\s*dead_code)',prev):continue
            m=re.match(r'^\s*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?(?:unsafe\s+)?fn\s+(\w+)',line)
            if m:all_defined.append((m.group(1),rel,i));def_lines.add(i)
        for i,line in enumerate(lines,1):
            if i not in def_lines:all_words|=set(re.findall(r'\b(\w+)\b',line))
    all_txt=all_source_text(root,{'.rs','.toml'})
    for fn,fpath,lineno in all_defined:
        if fn in RUST_SKIP or fn.startswith('test_') or fn.startswith('bench_'):continue
        if fn not in all_words:
            in_bc=bool(re.search(r'\b'+re.escape(fn)+r'\b',bc))
            in_all=all_txt.count(fn)>1
            c=score(fn,in_bc,False)
            if in_all:c=min(c+1,3)
            results.append({'type':'rust_dead','file':fpath,'line':lineno,'symbol':fn,
                            'confidence':c,'reason':_rust_reason(fn)})
    return results

def _rust_reason(fn):
    if fn.startswith('_'):return 'Prefixed _ (unused marker) — remove if truly dead'
    return 'Function defined but never called in this codebase'

# ── PHP ───────────────────────────────────────────────────────────────────────
PHP_SKIP={'__construct','__destruct','__toString','__get','__set','__isset',
          '__unset','__call','__callStatic','__invoke','__clone','__debugInfo',
          '__serialize','__unserialize','__sleep','__wakeup',
          'setUp','tearDown','handle','boot','register','index','show','store',
          'update','destroy','create','edit','up','down','run','execute','render',
          'toArray','jsonSerialize','toJson','offsetGet','offsetSet','offsetExists',
          'offsetUnset','count','rewind','current','key','valid','next',
          'configure','getSubscribedEvents','buildForm','configureOptions'}

def scan_php(root,bc):
    results=[]
    php_files=all_files(root,{'.php'})
    if not php_files:return results
    all_defined,all_words=[],set()
    for fpath in php_files:
        try:lines=fpath.read_text(errors='replace').splitlines()
        except:continue
        rel=os.path.relpath(fpath,root)
        def_lines=set()
        for i,line in enumerate(lines,1):
            m=re.match(r'^\s*(?:(?:public|protected|private|static|abstract|final)\s+)*function\s+(\w+)',line)
            if m:all_defined.append((m.group(1),rel,i));def_lines.add(i)
        for i,line in enumerate(lines,1):
            if i not in def_lines:all_words|=set(re.findall(r'\b(\w+)\b',line))
    for fn,fpath,lineno in all_defined:
        if fn in PHP_SKIP:continue
        if fn.startswith(('get','set','is','has','on','before','after','test')):continue
        if fn not in all_words:
            in_bc=bool(re.search(r'\b'+re.escape(fn)+r'\b',bc))
            c=score(fn,in_bc,False)
            results.append({'type':'php_dead','file':fpath,'line':lineno,'symbol':fn,
                            'confidence':c,'reason':_php_reason(fn)})
    return results

def _php_reason(fn):
    if fn.startswith('_'):return 'Convention-private method never called explicitly'
    return 'Function/method defined but never called in any PHP file'

# ── C / C++ ───────────────────────────────────────────────────────────────────
C_SKIP={'main','WinMain','wWinMain','wmain','DllMain','_start','__start',
        'init','setup','cleanup','free','malloc','calloc','realloc','strdup',
        'printf','fprintf','sprintf','snprintf','strlen','strcpy','strncpy',
        'strcat','strcmp','memcpy','memset','memmove','memcmp',
        'fopen','fclose','fread','fwrite','fseek','fflush',
        'abort','exit','atexit','assert','swap'}

def scan_c(root,bc):
    results=[]
    c_files=all_files(root,{'.c','.cpp','.cc','.cxx','.h','.hpp'})
    if not c_files:return results
    hdr_exts={'.h','.hpp','.hh','.hxx'}
    all_defined,all_words=[],set()
    for fpath in c_files:
        try:lines=fpath.read_text(errors='replace').splitlines()
        except:continue
        rel=os.path.relpath(fpath,root)
        def_lines=set()
        for i,line in enumerate(lines,1):
            s=line.rstrip()
            if s.endswith(';'):continue
            m=re.match(
                r'^(?:(?:static|inline|extern|virtual|explicit|constexpr|__attribute__[^)]*\))\s+)*'
                r'(?:[\w:~<>\*&\[\]\s]+\s+)?(\w+)\s*\([^;]*\)\s*(?:const\s*)?(?:noexcept\s*)?[\{\\]?\s*$',s)
            if m and not re.search(r'\bif\b|\bfor\b|\bwhile\b|\bswitch\b|\belse\b|^\s*#',line):
                fn=m.group(1)
                if len(fn)>2 and fn.isidentifier():
                    all_defined.append((fn,rel,i,fpath.suffix.lower() in hdr_exts))
                    def_lines.add(i)
        for i,line in enumerate(lines,1):
            if i not in def_lines:all_words|=set(re.findall(r'\b(\w+)\b',line))
    all_txt=all_source_text(root,{'.c','.cpp','.cc','.cxx','.h','.hpp','.cmake'})
    for fn,fpath,lineno,is_hdr in all_defined:
        if fn in C_SKIP:continue
        is_fp=any(re.search(p,fn) for p in FP_C_PATS)
        if is_fp:
            c=1
        elif fn not in all_words:
            in_bc=bool(re.search(r'\b'+re.escape(fn)+r'\b',bc))
            in_all=all_txt.count(fn)>1
            if in_all:continue
            c=score(fn,in_bc,is_hdr)
        else:
            continue
        results.append({'type':'c_dead','file':fpath,'line':lineno,'symbol':fn,
                        'confidence':c,'reason':_c_reason(fn,is_hdr,is_fp)})
    return results

def _c_reason(fn,is_hdr,is_fp):
    if is_fp:return 'Matches FFI/framework naming pattern — likely called indirectly'
    if is_hdr:return 'Declared in header — may be a public API for external consumers'
    return 'Function defined but no call site found in this codebase'

# ── Display ───────────────────────────────────────────────────────────────────
LANG_META={
    'js':    ('JS / TypeScript',C,'🟨'),'python':('Python',B,'🐍'),
    'go':    ('Go',C,'🐹'),            'ruby':  ('Ruby',R,'💎'),
    'java':  ('Java / Kotlin',Y,'☕'), 'css':   ('CSS / SCSS',M,'🎨'),
    'rust':  ('Rust',Y,'🦀'),          'php':   ('PHP',B,'🐘'),
    'c':     ('C / C++',G,'⚙️ '),
}
TYPE_LABELS={
    'unused_file':('Unused file',R),'unused_dep':('Unused package',Y),
    'unused_export':('Unused export',C),'missing_dep':('Missing dep',Y),
    'python_dead':('Dead code',R),'go_dead_func':('Dead function',R),
    'go_unused_import':('Unused import',Y),'ruby_dead':('Dead method',R),
    'java_dead':('Dead method',R),'css_dead_class':('Unused CSS class',M),
    'css_dead_id':('Unused CSS id',M),'rust_dead':('Dead function',R),
    'php_dead':('Dead function',R),'c_dead':('Dead function',R),
}
LANG_ORDER=['js','python','go','ruby','java','css','rust','php','c']

def _lang_of(t):
    if t.startswith(('unused','missing')):return 'js'
    for l in ['python','go','ruby','java','css','rust','php','c']:
        if t.startswith(l):return l
    return 'other'

def build_json_output(all_results, repo_name, show_low=False):
    """Build the structured JSON output from scan results."""
    high = [r for r in all_results if r.get('confidence', 2) == 3]
    med  = [r for r in all_results if r.get('confidence', 2) == 2]
    low  = [r for r in all_results if r.get('confidence', 2) == 1]

    # Collect unused files, exports, deps
    unused_files   = [r['file'] for r in all_results if r['type'] == 'unused_file']
    unused_exports = [{'file': r.get('file',''), 'symbol': r.get('symbol','')}
                      for r in all_results if r['type'] == 'unused_export']
    unused_deps    = [r.get('symbol', r.get('file',''))
                      for r in all_results if r['type'] == 'unused_dep']

    # Per-language summary
    by_lang = defaultdict(list)
    for r in all_results:
        by_lang[_lang_of(r['type'])].append(r)

    lang_scores = {}
    for lang in LANG_ORDER:
        items = by_lang.get(lang, [])
        if not items:
            continue
        h = sum(1 for i in items if i.get('confidence', 2) == 3)
        m = sum(1 for i in items if i.get('confidence', 2) == 2)
        l = sum(1 for i in items if i.get('confidence', 2) == 1)
        total = len(items)
        # normalise to 0-1 score (higher = more dead code detected)
        raw = (h * 1.0 + m * 0.5 + l * 0.1) / max(total, 1)
        lang_scores[lang] = round(raw, 4)

    # Build detailed analysis list
    visible = [r for r in all_results if show_low or r.get('confidence', 2) >= 2]
    analysis = []
    for r in visible:
        analysis.append({
            'type':       r['type'],
            'file':       str(r.get('file', '')),
            'symbol':     r.get('symbol', ''),
            'line':       r.get('line', None),
            'confidence': r.get('confidence', 2),
            'reason':     r.get('reason', ''),
        })

    total = len(all_results)
    counts = {'high': len(high), 'medium': len(med), 'low': len(low)}

    return {
        'status':        'complete',
        'repoType':      repo_name,
        'repoTypeScores': lang_scores,
        'unusedFiles':   unused_files,
        'unusedExports': unused_exports,
        'unusedDeps':    unused_deps,
        'summary':       f"{len(high)} HIGH, {len(med)} MED, {len(low)} LOW issues found in {repo_name}",
        'scores': {
            'repoPenalty':         round(min(1.0, (len(high) * 0.05 + len(med) * 0.02)), 4),
            'overall':             round(1.0 - min(1.0, (len(high) * 0.05 + len(med) * 0.02)), 4),
            'actionable':          round(len(high) / max(total, 1), 4),
            'countsByConfidence':  counts,
            'detectionReliability': round(len(high) / max(len(high) + len(low), 1), 4),
        },
        'analysis': analysis,
        'debug': {
            'analysisState': {
                'state': 'complete',
                'notes': f"Scanned {total} items across {len(by_lang)} language(s)",
            },
            'strongSignals':  {lang: s for lang, s in lang_scores.items() if s >= 0.5},
            'distribution': {
                'entropy':    round(_entropy(counts), 4),
                'separation': round(_separation(counts), 4),
            },
            'toolsRun':     list(by_lang.keys()),
            'toolsSuccess': [lang for lang in by_lang if by_lang[lang]],
        },
    }

def _entropy(counts):
    """Normalised Shannon entropy over confidence buckets."""
    import math
    total = sum(counts.values())
    if total == 0:
        return 0.0
    ent = 0.0
    for v in counts.values():
        if v > 0:
            p = v / total
            ent -= p * math.log2(p)
    # max entropy for 3 buckets = log2(3)
    return ent / math.log2(3) if ent else 0.0

def _separation(counts):
    """Ratio of HIGH to (HIGH+LOW) — how well-separated signal is from noise."""
    h, l = counts.get('high', 0), counts.get('low', 0)
    return h / max(h + l, 1)

SCANNERS={'js':scan_js,'python':scan_python,'go':scan_go,'ruby':scan_ruby,
          'java':scan_java,'css':scan_css,'rust':scan_rust,'php':scan_php,'c':scan_c}

def main():
    show_low='--show-low' in sys.argv
    args=[a for a in sys.argv[1:] if not a.startswith('--')]
    if args:repo_url=args[0].strip()
    else:
        try:repo_url=input("Enter GitHub repo URL: ").strip()
        except(EOFError,KeyboardInterrupt):
            print(json.dumps({"status":"cancelled","error":"User cancelled"}));sys.exit(0)
    if not repo_url:
        print(json.dumps({"status":"error","error":"No URL provided"}));sys.exit(1)
    if not repo_url.startswith('http'):repo_url=f"https://github.com/{repo_url}"
    repo_name=repo_url.rstrip('/').split('/')[-1].replace('.git','')
    tmp_dir=tempfile.mkdtemp(prefix='dead_scan_')
    try:
        r=run(['git','clone','--depth=1',repo_url,tmp_dir])
        if r.returncode!=0:
            print(json.dumps({"status":"error","error":r.stderr.strip()}));sys.exit(1)
        lang_counts=detect_languages(tmp_dir)
        if not lang_counts:
            print(json.dumps({"status":"error","error":"No supported files found"}));sys.exit(1)
        bc=collect_build_corpus(tmp_dir)
        all_results=[]
        tools_run=[]
        tools_success=[]
        for lang in LANG_ORDER:
            if lang not in lang_counts:continue
            tools_run.append(lang)
            try:
                found=SCANNERS[lang](tmp_dir,bc)
                all_results.extend(found)
                tools_success.append(lang)
            except Exception:pass
        output=build_json_output(all_results,repo_name,show_low)
        output['debug']['toolsRun']=tools_run
        output['debug']['toolsSuccess']=tools_success
        print(json.dumps(output,indent=2))
    finally:shutil.rmtree(tmp_dir,ignore_errors=True)

if __name__=='__main__':main()
