// Hi-fi Parser editor — split-pane: fields/selectors (left) · live test output (right)

function HFParserEditor({ nav, goto, params }) {
  const HF = getHF();
  const shop = params?.shop || 'vaga';

  const SHOPS = {
    vaga:         { lbl:'vaga.lt',         parser:'product.v3', version:3, health:99.8 },
    knygos:       { lbl:'knygos.lt',       parser:'product.v2', version:2, health:96.4 },
    patogupirkti: { lbl:'patogupirkti.lt', parser:'product.v4', version:4, health:82.1 },
    humanitas:    { lbl:'humanitas.lt',    parser:'product.v1', version:1, health:71.2 },
  };
  const cur = SHOPS[shop] || SHOPS.vaga;

  const initialFields = [
    { k:'title',       sel:'h1.product-title',                    attr:'text',    type:'text',    required:true,  multi:false, post:'trim',         val:'Sapiens: A Brief History of Humankind' },
    { k:'author',      sel:'.product-meta .author a',             attr:'text',    type:'text',    required:true,  multi:false, post:'trim',         val:'Yuval Noah Harari' },
    { k:'price',       sel:'.price-now .value',                   attr:'text',    type:'decimal', required:true,  multi:false, post:'parseDecimal', val:'14.99' },
    { k:'old_price',   sel:'.price-was .value',                   attr:'text',    type:'decimal', required:false, multi:false, post:'parseDecimal', val:null },
    { k:'isbn',        sel:'.product-specs [data-field="isbn"]',  attr:'text',    type:'text',    required:true,  multi:false, post:'digitsOnly',   val:'9780062316097' },
    { k:'publisher',   sel:'.product-specs [data-field="pub"]',   attr:'text',    type:'text',    required:false, multi:false, post:'trim',         val:'HarperCollins' },
    { k:'pages',       sel:'.product-specs [data-field="pages"]', attr:'text',    type:'integer', required:false, multi:false, post:'parseInt',     val:null },
    { k:'year',        sel:'.product-specs [data-field="year"]',  attr:'text',    type:'integer', required:false, multi:false, post:'parseInt',     val:'2014' },
    { k:'description', sel:'.product-description',                attr:'html',    type:'html',    required:false, multi:false, post:'sanitize',     val:'<p>From a renowned historian comes…</p>' },
    { k:'cover_url',   sel:'img.product-cover',                   attr:'src',     type:'url',     required:false, multi:false, post:'absoluteUrl',  val:'https://vaga.lt/covers/sapiens.jpg' },
  ];

  const [fields, setFields] = React.useState(initialFields);
  const [selectedIdx, setSelectedIdx] = React.useState(0);
  const [testUrl, setTestUrl] = React.useState('https://vaga.lt/knygos/sapiens-yuval-noah-harari');
  const [testing, setTesting] = React.useState(false);
  const [rightTab, setRightTab] = React.useState('preview');

  const sel = fields[selectedIdx];

  const updateField = (patch) => {
    setFields(prev => prev.map((f, i) => i === selectedIdx ? { ...f, ...patch } : f));
  };

  const addField = () => {
    const n = { k:`field_${fields.length+1}`, sel:'', attr:'text', type:'text', required:false, multi:false, post:'trim', val:null };
    setFields([...fields, n]);
    setSelectedIdx(fields.length);
  };

  const removeField = () => {
    if (fields.length <= 1) return;
    const next = fields.filter((_, i) => i !== selectedIdx);
    setFields(next);
    setSelectedIdx(Math.max(0, selectedIdx - 1));
  };

  const runTest = () => {
    setTesting(true);
    setTimeout(() => setTesting(false), 900);
  };

  const okCount = fields.filter(f => f.val != null).length;
  const missingRequired = fields.filter(f => f.required && f.val == null).length;

  return (
    <HFShell {...nav} activePage={null}
      title={<span style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <span style={{ fontSize: 22, fontWeight: 700, color: HF.ink, letterSpacing: -0.3 }}>Parser editor</span>
        <HFPill tone="accent"><span style={{ fontFamily: HF.mono }}>{cur.parser}</span></HFPill>
        <HFPill tone="warn">unsaved changes</HFPill>
      </span>}
      subtitle={<span style={{ fontFamily: HF.mono, fontSize: 12.5, color: HF.ink3 }}>
        shop={shop} · {fields.length} fields · {fields.filter(f=>f.required).length} required · health {cur.health}%
      </span>}
      breadcrumb={<>
        <a href="#" onClick={(e)=>{e.preventDefault(); goto('shops');}} style={{ color: HF.ink3, textDecoration:'none' }}>Shops</a>
        <span style={{ color: HF.ink5 }}>/</span>
        <a href="#" onClick={(e)=>{e.preventDefault(); goto('shop-detail', {shop});}} style={{ color: HF.ink3, textDecoration:'none', fontFamily: HF.mono }}>{cur.lbl}</a>
        <span style={{ color: HF.ink5 }}>/</span>
        <span style={{ color: HF.ink, fontWeight: 500 }}>Parser</span>
      </>}
      actions={<>
        <HFButton onClick={runTest}><span style={{display:'flex'}}>{HF_ICONS.play}</span> Test now</HFButton>
        <HFButton>History</HFButton>
        <HFButton variant="primary">Save & deploy</HFButton>
      </>}
    >
      {/* Split pane */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'minmax(380px, 1.1fr) 2fr',
        gap: HF.gap, alignItems: 'stretch',
        minHeight: 620,
      }}>
        {/* ═══════════ LEFT: fields list + config ═══════════ */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: HF.gap }}>
          <HFCard title="Fields" sub={`${okCount}/${fields.length} extracting · ${missingRequired} required missing`}
            action={<HFButton size="sm" onClick={addField}><span style={{display:'flex'}}>{HF_ICONS.plus}</span> Add field</HFButton>}>
            <div style={{ maxHeight: 360, overflow: 'auto' }} className="hf-scroll">
              {fields.map((f, i) => {
                const active = i === selectedIdx;
                const tone = f.val == null ? (f.required ? 'err' : 'neutral') : 'ok';
                return (
                  <div key={i} onClick={() => setSelectedIdx(i)} style={{
                    display: 'grid',
                    gridTemplateColumns: '18px 1fr auto',
                    alignItems: 'center', gap: 10,
                    padding: '9px 14px',
                    borderBottom: `1px solid ${HF.borderFaint}`,
                    background: active ? HF.accentSoft : 'transparent',
                    borderLeft: `3px solid ${active ? HF.accent : 'transparent'}`,
                    cursor: 'pointer',
                  }}
                  onMouseEnter={(e) => { if (!active) e.currentTarget.style.background = HF.subtle; }}
                  onMouseLeave={(e) => { if (!active) e.currentTarget.style.background = 'transparent'; }}>
                    <HFDot tone={tone} size={7}/>
                    <div style={{ minWidth: 0 }}>
                      <div style={{
                        fontFamily: HF.mono, fontSize: 12,
                        color: active ? HF.accentInk : HF.ink, fontWeight: active ? 600 : 500,
                        display: 'flex', alignItems: 'center', gap: 6,
                      }}>
                        {f.k}
                        {f.required && <span style={{ color: HF.errInk, fontSize: 10 }}>*</span>}
                      </div>
                      <div style={{ fontFamily: HF.mono, fontSize: 10.5, color: HF.ink3, marginTop: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {f.sel || '—'}
                      </div>
                    </div>
                    <span style={{ fontFamily: HF.mono, fontSize: 10.5, color: HF.ink4 }}>{f.type}</span>
                  </div>
                );
              })}
            </div>
          </HFCard>

          {/* Selected field editor */}
          <HFCard title={<span style={{ fontFamily: HF.mono }}>{sel.k}</span>}
            sub="selector & extraction config"
            action={
              <HFButton size="sm" variant="danger" onClick={removeField}>Remove</HFButton>
            }>
            <div style={{ padding: 14 }}>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                <HFField label="Field name" required>
                  <HFInput value={sel.k} onChange={(v) => updateField({ k: v })} mono/>
                </HFField>
                <HFField label="Type">
                  <HFSelect value={sel.type} onChange={(v) => updateField({ type: v })} options={[
                    'text','decimal','integer','url','html','boolean','date',
                  ]}/>
                </HFField>
              </div>
              <HFField label="CSS selector" hint="jQuery-style; supports :nth-child, [attr=...], etc.">
                <HFInput value={sel.sel} onChange={(v) => updateField({ sel: v })} mono placeholder=".product .title"/>
              </HFField>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                <HFField label="Attribute" hint="text, html, or an attr name">
                  <HFSelect value={sel.attr} onChange={(v) => updateField({ attr: v })} options={[
                    { value:'text', label:'text content' },
                    { value:'html', label:'inner HTML' },
                    { value:'src',  label:'attr: src' },
                    { value:'href', label:'attr: href' },
                    { value:'data-value', label:'attr: data-value' },
                  ]}/>
                </HFField>
                <HFField label="Post-process">
                  <HFSelect value={sel.post} onChange={(v) => updateField({ post: v })} options={[
                    'trim','parseDecimal','parseInt','digitsOnly','sanitize','absoluteUrl','lowercase','none',
                  ]}/>
                </HFField>
              </div>
              <div style={{ display: 'flex', gap: 18, marginTop: 4 }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12.5, color: HF.ink2, cursor: 'pointer' }}>
                  <input type="checkbox" checked={sel.required} onChange={(e) => updateField({ required: e.target.checked })}
                    style={{ margin: 0, accentColor: HF.accent }}/>
                  Required
                </label>
                <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12.5, color: HF.ink2, cursor: 'pointer' }}>
                  <input type="checkbox" checked={sel.multi} onChange={(e) => updateField({ multi: e.target.checked })}
                    style={{ margin: 0, accentColor: HF.accent }}/>
                  Multi (array)
                </label>
              </div>
            </div>
          </HFCard>
        </div>

        {/* ═══════════ RIGHT: test output ═══════════ */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: HF.gap }}>
          {/* Test URL bar */}
          <HFCard padding={12}>
            <div style={{ padding: 2 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                <span style={{ fontSize: 11, color: HF.ink3, fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.5 }}>Test URL</span>
                <span style={{ marginLeft: 'auto', fontSize: 11, color: HF.ink3, fontFamily: HF.mono }}>
                  last test: {testing ? 'running…' : '2m ago · 9/10 ok · 1.4s'}
                </span>
              </div>
              <div style={{ display: 'flex', gap: 6 }}>
                <HFInput value={testUrl} onChange={setTestUrl} mono style={{ flex: 1 }}/>
                <HFButton variant="primary" onClick={runTest}>
                  {testing ? '…running' : <><span style={{display:'flex'}}>{HF_ICONS.play}</span>Run test</>}
                </HFButton>
              </div>
            </div>
          </HFCard>

          {/* Tab strip for right pane */}
          <div style={{
            display: 'flex', gap: 2, borderBottom: `1px solid ${HF.border}`,
            marginBottom: -HF.gap, paddingBottom: 0,
          }}>
            {[
              ['preview',    'Extracted'],
              ['selector',   'Selector match'],
              ['dom',        'DOM sample'],
              ['diagnostics','Diagnostics'],
            ].map(([v, l]) => (
              <button key={v} onClick={() => setRightTab(v)} style={{
                padding: '8px 14px', fontSize: 12.5, fontFamily: HF.sans,
                background: 'transparent', border: 'none', cursor: 'pointer',
                color: rightTab === v ? HF.accent : HF.ink3,
                fontWeight: rightTab === v ? 600 : 500,
                borderBottom: `2px solid ${rightTab === v ? HF.accent : 'transparent'}`,
                marginBottom: -1,
              }}>{l}</button>
            ))}
          </div>

          {/* Right pane content */}
          {rightTab === 'preview' && (
            <HFCard title="Extracted fields" sub="after selector match + post-processing">
              <div style={{ fontFamily: HF.mono, fontSize: 11.5, background: HF.subtle, borderTop: `1px solid ${HF.borderFaint}` }}>
                <div style={{ padding: '10px 14px 4px', color: HF.ink3 }}>
                  <span style={{ color: HF.ink4 }}>// JSON output · posted to bookscraper.books</span>
                </div>
                <div style={{ padding: '4px 14px 14px', lineHeight: 1.85, color: HF.ink2 }}>
                  <div><span style={{ color: HF.ink4 }}>&#123;</span></div>
                  {fields.map((f, i) => {
                    const ok = f.val != null;
                    const val = ok
                      ? (f.type === 'html'    ? <span style={{ color: HF.ink3 }}>"&lt;p&gt;…&lt;/p&gt;"</span>
                        : f.type === 'decimal' || f.type === 'integer' ? <span style={{ color: '#b45309' }}>{f.val}</span>
                        : <span style={{ color: HF.okInk }}>"{f.val}"</span>)
                      : <span style={{ color: HF.ink4 }}>null</span>;
                    const warn = !ok && f.required;
                    return (
                      <div key={i} style={{
                        padding: '2px 0 2px 18px',
                        background: warn ? HF.errSoft : i === selectedIdx ? HF.accentSoft : 'transparent',
                        borderLeft: warn ? `2px solid ${HF.err}` : i === selectedIdx ? `2px solid ${HF.accent}` : '2px solid transparent',
                        marginLeft: -14, paddingLeft: 30, position: 'relative',
                      }}>
                        <span style={{ color: '#6b7280' }}>"{f.k}"</span>
                        <span style={{ color: HF.ink4 }}>: </span>
                        {val}
                        <span style={{ color: HF.ink4 }}>{i === fields.length - 1 ? '' : ','}</span>
                        {warn && <span style={{ color: HF.errInk, fontSize: 10.5, marginLeft: 10 }}>  // ⚠ required, not matched</span>}
                      </div>
                    );
                  })}
                  <div><span style={{ color: HF.ink4 }}>&#125;</span></div>
                </div>
              </div>
            </HFCard>
          )}

          {rightTab === 'selector' && (
            <HFCard title="Selector match"
              sub={<span style={{ fontFamily: HF.mono }}>{sel.sel || '— no selector —'}</span>}>
              <div style={{ padding: 14 }}>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10, marginBottom: 14 }}>
                  {[
                    ['Matches', sel.val != null ? '1' : '0', sel.val != null ? 'ok' : 'err'],
                    ['Post-processed', sel.val != null ? 'yes' : '—', 'neutral'],
                    ['Shape', sel.multi ? 'array' : 'scalar', 'neutral'],
                  ].map(([l, v, tone]) => (
                    <div key={l} style={{
                      padding: 10, background: HF.subtle,
                      border: `1px solid ${HF.border}`, borderRadius: 6,
                    }}>
                      <div style={{ fontSize: 10.5, color: HF.ink4, fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.5 }}>{l}</div>
                      <div style={{
                        fontFamily: HF.mono, fontSize: 16, marginTop: 4,
                        color: tone === 'ok' ? HF.okInk : tone === 'err' ? HF.errInk : HF.ink,
                        fontWeight: 500, fontVariantNumeric: 'tabular-nums',
                      }}>{v}</div>
                    </div>
                  ))}
                </div>
                <div style={{ fontSize: 11.5, color: HF.ink3, fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 6 }}>Matched node</div>
                <div style={{
                  fontFamily: HF.mono, fontSize: 11.5, background: HF.subtle,
                  border: `1px solid ${HF.border}`, borderRadius: 6,
                  padding: 10, color: HF.ink2, lineHeight: 1.75,
                }}>
                  <span style={{ color: HF.ink4 }}>&lt;</span>
                  <span style={{ color: HF.accentInk }}>h1</span>
                  <span style={{ color: HF.ink4 }}> </span>
                  <span style={{ color: HF.warnInk }}>class</span>
                  <span style={{ color: HF.ink4 }}>=</span>
                  <span style={{ color: HF.okInk }}>"product-title"</span>
                  <span style={{ color: HF.ink4 }}>&gt;</span>
                  <br/>
                  <span style={{ paddingLeft: 16 }}>Sapiens: A Brief History of Humankind</span>
                  <br/>
                  <span style={{ color: HF.ink4 }}>&lt;/</span>
                  <span style={{ color: HF.accentInk }}>h1</span>
                  <span style={{ color: HF.ink4 }}>&gt;</span>
                </div>
                <div style={{ fontSize: 11.5, color: HF.ink3, fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.5, marginTop: 14, marginBottom: 6 }}>XPath equivalent</div>
                <div style={{ fontFamily: HF.mono, fontSize: 11.5, color: HF.ink2, padding: '8px 10px', background: HF.bg, border: `1px solid ${HF.border}`, borderRadius: 6 }}>
                  //h1[contains(@class, 'product-title')]
                </div>
              </div>
            </HFCard>
          )}

          {rightTab === 'dom' && (
            <HFCard title="DOM sample" sub="live fetched HTML · highlighted nodes match the active selector">
              <div style={{
                fontFamily: HF.mono, fontSize: 11, lineHeight: 1.8,
                padding: 14, color: HF.ink2, maxHeight: 420, overflow: 'auto',
                background: HF.subtle, borderTop: `1px solid ${HF.borderFaint}`,
              }} className="hf-scroll">
                {[
                  ['<!DOCTYPE html>', 'c'],
                  ['<html lang="lt">', 't'],
                  ['  <body>', 't'],
                  ['    <main class="product">', 't'],
                  ['      <h1 class="product-title">Sapiens: A Brief History of Humankind</h1>', 'hit'],
                  ['      <div class="product-meta">', 't'],
                  ['        <span class="author"><a href="/autorius/harari">Yuval Noah Harari</a></span>', 'sub'],
                  ['      </div>', 't'],
                  ['      <div class="price-now"><span class="value">14.99</span> €</div>', 'sub'],
                  ['      <div class="price-was" hidden><span class="value"></span></div>', 'miss'],
                  ['      <dl class="product-specs">', 't'],
                  ['        <dt>ISBN</dt><dd data-field="isbn">9780062316097</dd>', 'sub'],
                  ['        <dt>Leidėjas</dt><dd data-field="pub">HarperCollins</dd>', 'sub'],
                  ['      </dl>', 't'],
                  ['      <div class="product-description">', 'sub'],
                  ['        <p>From a renowned historian comes…</p>', 'sub'],
                  ['      </div>', 'sub'],
                  ['      <img class="product-cover" src="/covers/sapiens.jpg"/>', 'sub'],
                  ['    </main>', 't'],
                  ['  </body>', 't'],
                  ['</html>', 't'],
                ].map(([line, k], i) => {
                  const bg = k === 'hit' ? HF.accentSoft2 : k === 'miss' ? HF.errSoft : 'transparent';
                  const color = k === 'hit' ? HF.accentInk : k === 'miss' ? HF.errInk : k === 'c' ? HF.ink4 : HF.ink2;
                  return (
                    <div key={i} style={{
                      padding: '0 10px', background: bg, color, whiteSpace: 'pre',
                      borderLeft: k === 'hit' ? `3px solid ${HF.accent}` : k === 'miss' ? `3px solid ${HF.err}` : '3px solid transparent',
                      marginLeft: -14, paddingLeft: 14, display: 'flex',
                    }}>
                      <span style={{ width: 28, color: HF.ink5, userSelect: 'none', display: 'inline-block', textAlign: 'right', paddingRight: 10 }}>{i + 1}</span>
                      <span>{line}</span>
                    </div>
                  );
                })}
              </div>
            </HFCard>
          )}

          {rightTab === 'diagnostics' && (
            <HFCard title="Diagnostics" sub="fetch + parse timings, errors, warnings">
              <div style={{ padding: 14 }}>
                {[
                  { l:'DNS + TCP',    v:'42ms',  tone:'ok' },
                  { l:'TTFB',         v:'318ms', tone:'ok' },
                  { l:'HTML download',v:'612ms', tone:'ok' },
                  { l:'Parse + extract', v:'44ms', tone:'ok' },
                  { l:'Total',        v:'1.42s', tone:'ok' },
                ].map((r, i) => (
                  <div key={i} style={{
                    display: 'flex', justifyContent: 'space-between',
                    padding: '7px 0', borderBottom: i === 4 ? 'none' : `1px solid ${HF.borderFaint}`,
                    fontFamily: HF.mono, fontSize: 12,
                  }}>
                    <span style={{ color: HF.ink2 }}>{r.l}</span>
                    <span style={{ color: HF.okInk, fontVariantNumeric: 'tabular-nums' }}>{r.v}</span>
                  </div>
                ))}
                <div style={{ marginTop: 14, fontSize: 11.5, color: HF.ink3, fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 6 }}>Warnings</div>
                <div style={{
                  padding: 10, background: HF.warnSoft, border: `1px solid ${HF.warnBorder}`,
                  borderRadius: 6, fontSize: 12, color: HF.warnInk, fontFamily: HF.mono,
                  display: 'flex', gap: 8, alignItems: 'flex-start',
                }}>
                  <span>⚠</span>
                  <div>
                    <div style={{ fontWeight: 500, marginBottom: 2 }}>price.old_price: selector matched 0 nodes</div>
                    <div style={{ color: HF.ink3, fontSize: 11.5 }}>The <span style={{ color: HF.ink }}>.price-was</span> element exists but is hidden. Consider <span style={{ color: HF.ink }}>:not([hidden])</span> or mark field optional.</div>
                  </div>
                </div>
              </div>
            </HFCard>
          )}
        </div>
      </div>

      {/* Deploy bar */}
      <div style={{
        position: 'sticky', bottom: -48, marginTop: HF.gap, marginBottom: -48,
        background: HF.surface, border: `1px solid ${HF.border}`, borderRadius: HF.r3,
        padding: '12px 16px', boxShadow: '0 -2px 12px rgba(16,24,40,.04)',
        display: 'flex', alignItems: 'center', gap: 14,
      }}>
        <HFDot tone="warn" pulse size={8}/>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 12.5, fontWeight: 500, color: HF.ink }}>Unsaved changes</div>
          <div style={{ fontSize: 11.5, color: HF.ink3, fontFamily: HF.mono, marginTop: 1 }}>
            2 fields edited · last tested 2m ago · would deploy as <span style={{ color: HF.ink }}>product.v{cur.version + 1}</span>
          </div>
        </div>
        <HFButton>Discard</HFButton>
        <HFButton>Save as draft</HFButton>
        <HFButton variant="primary">Save & deploy</HFButton>
      </div>
    </HFShell>
  );
}

window.HFParserEditor = HFParserEditor;
