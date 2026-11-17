"""Participant amount, share and operation drill views use one exclusive expense cut."""
from pathlib import Path
import json,math,os,shutil,unittest
from playwright.sync_api import sync_playwright
HTML=(Path(__file__).resolve().parents[1]/'index.html').read_text()
BASE='http://127.0.0.1:9893/'

class ParticipantDistribution(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.p=sync_playwright().start();exe=os.environ.get('CHROMIUM_EXECUTABLE') or shutil.which('chromium') or shutil.which('chromium-browser')
  cls.browser=cls.p.chromium.launch(headless=True,**({'executable_path':exe} if exe else {}))
 @classmethod
 def tearDownClass(cls):cls.browser.close();cls.p.stop()
 def setUp(self):
  self.context=self.browser.new_context(timezone_id='Europe/Moscow',viewport={'width':1440,'height':1100},service_workers='block')
  self.context.route('**/*',lambda r:r.fulfill(status=200,content_type='text/html',body=HTML) if r.request.url==BASE else r.abort())
  self.page=self.context.new_page();self.errors=[];self.page.on('pageerror',lambda error:self.errors.append(str(error)));self.page.on('dialog',lambda d:d.accept())
  self.page.goto(BASE,wait_until='domcontentloaded');self.page.wait_for_function("typeof v176RenderParticipantDistribution==='function'")
  self.evaluate('''
  session=null;localRecoveryBlocked=false;window.__FINANCE_BRIDGE__=null;localStorage.clear();state=blankState();saveAll=async()=>true;
  today=()=> '2026-11-18';month=()=> '2026-11';const expense=(id,date,amount,category,beneficiary)=>({id,date,amount,type:'expense',category,beneficiary,who:'Общее',store:'Тест',comment:'Без реальных данных',created_at:'2026-11-01T10:00:00.000Z',updated_at:'2026-11-01T10:00:00.000Z'});
  state.entries=[expense('sergey','2026-11-05',200,'Продукты','Сергей'),expense('general','2026-11-06',100,'Продукты','Общее'),expense('car','2026-11-07',50,'Бензин','Сергей'),expense('loan','2026-11-08',150,'Кредит','Общее'),expense('prior-sergey','2026-10-05',50,'Продукты','Сергей'),expense('deleted','2026-10-05',999,'Продукты','Виктория'),{id:'income',date:'2026-11-05',amount:99999,type:'income',who:'Сергей',category:'Доход'},{id:'transfer',date:'2026-11-05',amount:999,type:'transfer',from:'Карта',to:'Наличные'}];state.deletedEntries['deleted']='2026-11-17T10:00:00.000Z';
  showApp();go('analytics');document.getElementById('analyticsMonth').value='2026-11';document.getElementById('analyticsScope').value='month';renderAnalytics();window.distributionOriginal=JSON.stringify(state.entries);
  ''')
 def tearDown(self):self.context.close();self.assertEqual(self.errors,[])
 def evaluate(self,code):return self.page.evaluate('async()=>{'+code+'}')
 def controls(self,kind,key):
  selector={'bar':'#aPeopleChart button','legend':'#peopleLegend button','segment':'#peopleDonut path'}[kind]
  return self.page.locator(selector+'[data-v176-key='+json.dumps(key,ensure_ascii=False)+']')
 def select_view(self,view):self.page.locator('#v185LinearTab' if view=='linear' else '#v185CircularTab').click()
 def ring_click(self,key):
  geometry=self.evaluate('''const rows=v86TargetTotals(v130AnalyticsExpenses()).filter(([,v])=>v>0),total=sum(v130AnalyticsExpenses());let start=0;for(const [key,amount]of rows){if(key===%s){const r=document.getElementById('peopleDonut').getBoundingClientRect(),angle=(start+amount/total*180-90)*Math.PI/180;return {x:r.x+r.width/2+Math.cos(angle)*r.width*.37,y:r.y+r.height/2+Math.sin(angle)*r.height*.37}}start+=amount/total*360}'''%json.dumps(key))
  self.page.mouse.click(geometry['x'],geometry['y'])
 def drill(self):return self.evaluate("return {key:v96DrillContext?.key,scope:v96DrillContext?.scope,ids:[...document.querySelectorAll('#v84DrillEntries [data-v141-operation-id]')].map(e=>e.dataset.v141OperationId).sort(),total:document.getElementById('v96DrillTotal').textContent};")
 def test_common_heading_higher_position_and_same_exclusive_values_colors(self):
  data=self.evaluate('''const card=document.getElementById('v176ParticipantDistribution'),keys=selector=>[...document.querySelectorAll(selector)].map(e=>e.dataset.v176Key),barColors=Object.fromEntries([...document.querySelectorAll('#aPeopleChart button')].map(e=>[e.dataset.v176Key,e.querySelector('i').style.background])),legendColors=Object.fromEntries([...document.querySelectorAll('#peopleLegend button')].map(e=>[e.dataset.v176Key,e.querySelector('i').style.background])),svgColors=Object.fromEntries([...document.querySelectorAll('#peopleDonut path')].map(e=>[e.dataset.v176Key,e.getAttribute('fill')]));return {heading:document.getElementById('v176DistributionTitle').textContent,beforeCategories:!!(card.compareDocumentPosition(document.getElementById('v165CategorySummary'))&Node.DOCUMENT_POSITION_FOLLOWING),beforeStores:!!(card.compareDocumentPosition(document.getElementById('v163AnalyticsStores'))&Node.DOCUMENT_POSITION_FOLLOWING),bars:keys('#aPeopleChart button'),legend:keys('#peopleLegend button'),segments:keys('#peopleDonut path'),amounts:Object.fromEntries([...document.querySelectorAll('#peopleDonut path')].map(e=>[e.dataset.v176Key,Number(e.dataset.v176Amount)])),barColors,legendColors,svgColors,total:document.getElementById('peopleDonutTotal').textContent,unchanged:JSON.stringify(state.entries)===distributionOriginal};''')
  self.assertEqual(data['heading'],'Распределение расходов среди участников');self.assertTrue(data['beforeCategories'] and data['beforeStores'])
  self.assertEqual(data['bars'],data['legend']);self.assertEqual(data['bars'],data['segments'])
  self.assertEqual(data['amounts'],{'Сергей':200,'Кредиты и рассрочки':150,'Общее':100,'Автомобиль':50});self.assertEqual(data['total'],'500 ₽');self.assertTrue(data['unchanged'])
  for key,color in data['svgColors'].items():
   computed=self.controls('segment',key).evaluate('e=>getComputedStyle(e).fill')
   self.assertEqual(computed,data['barColors'][key]);self.assertEqual(computed,data['legendColors'][key])
 def test_bar_legend_and_painted_sector_open_exact_same_operations(self):
  expected={'Сергей':['sergey'],'Кредиты и рассрочки':['loan'],'Общее':['general'],'Автомобиль':['car']}
  for key,ids in expected.items():
   views=[]
   for kind in ['bar','legend','segment']:
    self.select_view('linear' if kind=='bar' else 'circular')
    if kind=='segment':
     self.page.locator('#peopleDonut').scroll_into_view_if_needed();self.ring_click(key)
    else:self.controls(kind,key).click()
    views.append(self.drill());self.page.locator('#v84DrillModal .v84-close').click()
   for view in views:self.assertEqual(view['ids'],ids);self.assertEqual(view['scope'],'month');self.assertEqual(view['key'],key)
   self.assertEqual(views[0],views[1]);self.assertEqual(views[0],views[2])
 def test_hole_and_empty_area_ignore_click_and_keyboard_restores_segment_focus(self):
  self.select_view('circular')
  self.page.locator('#peopleDonut').scroll_into_view_if_needed();rect=self.page.locator('#peopleDonut').bounding_box();self.page.mouse.click(rect['x']+rect['width']/2,rect['y']+rect['height']/2)
  self.assertFalse(self.page.locator('#v84DrillModal').evaluate("e=>e.classList.contains('open')"))
  self.page.mouse.click(rect['x']+2,rect['y']+2);self.assertFalse(self.page.locator('#v84DrillModal').evaluate("e=>e.classList.contains('open')"))
  segment=self.controls('segment','Сергей');segment.focus();segment.press('Enter');self.assertEqual(self.drill()['ids'],['sergey']);self.page.keyboard.press('Escape');self.assertTrue(segment.evaluate('e=>document.activeElement===e'))
  segment.press('Space');self.assertEqual(self.drill()['ids'],['sergey']);self.page.keyboard.press('Escape')
  legend=self.controls('legend','Автомобиль');legend.focus();legend.press('Enter');self.assertEqual(self.drill()['ids'],['car']);self.page.keyboard.press('Escape');self.assertTrue(legend.evaluate('e=>document.activeElement===e'))
 def test_all_time_sector_edit_delete_preserves_scope_and_redraws_both_views(self):
  self.evaluate("document.getElementById('analyticsScope').value='all';renderAnalytics();")
  self.select_view('circular')
  self.controls('segment','Сергей').focus();self.controls('segment','Сергей').press('Enter');self.assertEqual(self.drill()['ids'],['prior-sergey','sergey']);self.assertEqual(self.drill()['scope'],'all')
  self.evaluate("v96EditFromDrill('prior-sergey');document.getElementById('xAmount').value='75';await saveEdit();")
  self.assertEqual(self.drill()['total'],'275,00 ₽');self.assertEqual(self.drill()['scope'],'all');self.assertEqual(self.controls('segment','Сергей').get_attribute('data-v176-amount'),'275')
  self.evaluate("v96DeleteFromDrill('prior-sergey');await new Promise(requestAnimationFrame);")
  self.assertEqual(self.drill()['ids'],['sergey']);self.assertEqual(self.drill()['scope'],'all');self.assertEqual(self.controls('segment','Сергей').get_attribute('data-v176-amount'),'200');self.assertIn('200',self.controls('legend','Сергей').inner_text())
  self.page.keyboard.press('Escape');self.assertTrue(self.controls('segment','Сергей').evaluate('e=>document.activeElement===e'))
  self.assertTrue(self.page.locator('#v185CircularPanel').is_visible());self.assertFalse(self.page.locator('#v185LinearPanel').is_visible())
 def test_zero_single_and_unsafe_names_have_finite_safe_geometry(self):
  zero=self.evaluate("state.entries=[];renderAnalytics();return {paths:document.querySelectorAll('#peopleDonut path').length,bars:document.querySelectorAll('#aPeopleChart button').length,legend:document.querySelectorAll('#peopleLegend button').length,total:document.getElementById('peopleDonutTotal').textContent,text:document.getElementById('v176ParticipantDistribution').innerText};")
  self.assertEqual((zero['paths'],zero['bars'],zero['legend'],zero['total']),(0,0,0,'0 ₽'));self.assertNotRegex(zero['text'],'NaN|Infinity')
  self.evaluate('''state.entries=[{id:'unsafe',type:'expense',date:'2026-11-05',amount:.01,category:'Продукты',beneficiary:'<img src=x onerror=alert(1)>',who:'Общее'}];renderAnalytics();''')
  self.assertEqual(self.page.locator('#peopleDonut path').count(),1);self.assertEqual(self.page.locator('#v176ParticipantDistribution img').count(),0);self.assertIn('<img',self.page.locator('#peopleLegend').inner_text());self.assertNotRegex(self.page.locator('#peopleDonut path').get_attribute('d'),'NaN|Infinity')
  self.select_view('circular')
  self.page.locator('#peopleDonut').scroll_into_view_if_needed();self.ring_click('<img src=x onerror=alert(1)>');self.assertEqual(self.drill()['ids'],['unsafe'])
 def test_distribution_fits_small_and_large_screens(self):
  self.select_view('circular')
  for width in [320,390,600,768,1024,1280,1440,1920]:
   self.page.set_viewport_size({'width':width,'height':1000})
   self.assertFalse(self.page.evaluate('document.documentElement.scrollWidth>document.documentElement.clientWidth+1'),width)
   self.assertFalse(self.page.locator('#v176ParticipantDistribution').evaluate('e=>e.scrollWidth>e.clientWidth+1'),width)
   self.assertGreaterEqual(self.controls('legend','Сергей').bounding_box()['height'],44)

 def test_view_tabs_keyboard_and_route_refresh_preserve_choice_without_saving(self):
  before=self.evaluate("window.v185SaveCalls=0;saveAll=async()=>{v185SaveCalls++;return true};return JSON.stringify(state);")
  linear=self.page.locator('#v185LinearTab');circular=self.page.locator('#v185CircularTab')
  self.assertTrue(self.page.locator('#v185LinearPanel').is_visible());self.assertFalse(self.page.locator('#v185CircularPanel').is_visible())
  linear.focus();linear.press('ArrowRight');self.assertTrue(circular.evaluate('e=>document.activeElement===e'))
  self.assertEqual(circular.get_attribute('aria-selected'),'true');self.assertEqual(linear.get_attribute('tabindex'),'-1')
  circular.press('ArrowRight');self.assertTrue(linear.evaluate('e=>document.activeElement===e'))
  linear.press('End');self.assertTrue(circular.evaluate('e=>document.activeElement===e'))
  circular.press('Home');self.assertTrue(linear.evaluate('e=>document.activeElement===e'))
  linear.press('ArrowLeft');self.assertTrue(circular.evaluate('e=>document.activeElement===e'))
  self.evaluate("go('home');go('analytics');renderAll();")
  self.assertTrue(self.page.locator('#v185CircularPanel').is_visible());self.assertFalse(self.page.locator('#v185LinearPanel').is_visible())
  self.assertEqual(self.page.locator('#v176ParticipantDistribution [role=tabpanel]:visible').count(),1)
  after=self.evaluate("return {state:JSON.stringify(state),saved:v185SaveCalls};")
  self.assertEqual(after['state'],before);self.assertEqual(after['saved'],0)

 def test_insights_group_canonical_categories_and_exclude_separate_car_and_loan_buckets(self):
  result=self.evaluate('''
   const e=(id,amount,category,beneficiary,fields={})=>({id,type:'expense',date:'2026-11-05',amount,category,beneficiary,who:'Общее',...fields});
   state.entries=[e('sport-a',.10,'Спорт','Сергей'),e('sport-b',.20,'Фитнес','Сергей'),e('food',.29,'Продукты','Сергей'),
    e('tie-z',20,'Бета','Виктория'),e('tie-a',20,'Альфа','Виктория'),
    e('shared-a',2,'Дом','Семья'),e('shared-b',3,'Дом и быт','Общие расходы'),
    e('unknown',4,'Продукты','',{who:''}),e('car',999,'Бензин','Сергей'),e('car-direction',999,'Продукты','Автомобиль'),
    e('credit',999,'Кредит','Сергей'),e('credit-direction',999,'Продукты','Кредиты и рассрочки'),
    e('linked-credit',999,'Бензин','Сергей',{installmentId:'test'})];
   renderAnalytics();return {rows:v185ParticipantCategoryInsights(),dom:[...document.querySelectorAll('#v185ParticipantInsights>li[data-v185-participant]')].map(e=>({key:e.dataset.v185Participant,category:e.dataset.v185Category,text:e.textContent})),total:document.getElementById('peopleDonut').dataset.total};
  ''')
  rows={row['key']:row for row in result['rows']}
  self.assertEqual(set(rows),{'Сергей','Виктория','Общее','Не указано'})
  self.assertEqual((rows['Сергей']['categoryKey'],rows['Сергей']['amount'],rows['Сергей']['total']),('Спорт и здоровье',.3,.59))
  self.assertEqual((rows['Виктория']['categoryLabel'],rows['Виктория']['amount']),('Альфа',20))
  self.assertEqual((rows['Общее']['categoryKey'],rows['Общее']['amount']),('Дом',5))
  self.assertTrue(all(row['category']==rows[row['key']]['categoryKey'] for row in result['dom']))
  self.assertTrue(all('Больше всего' in row['text'] for row in result['dom']))

 def test_current_month_tombstones_and_revived_records_match_chart_insight_and_drill(self):
  self.evaluate('''
   const e=(id,amount,category,updated)=>({id,type:'expense',date:'2026-11-05',amount,category,beneficiary:'Сергей',updated_at:updated});
   state.entries=[e('live',10,'Продукты','2026-11-01T10:00:00Z'),e('deleted',999,'Дом','2026-11-01T10:00:00Z'),e('revived',20,'Дом','2026-11-03T10:00:00Z')];
   state.deletedEntries={'deleted':'2026-11-02T10:00:00Z','revived':'2026-11-02T10:00:00Z'};renderAnalytics();
  ''')
  row=self.evaluate("return {rows:v185ParticipantCategoryInsights(),total:document.getElementById('peopleDonut').dataset.total,amount:document.querySelector('#peopleDonut path').dataset.v176Amount};")
  self.assertEqual((row['rows'][0]['categoryKey'],row['rows'][0]['amount'],row['rows'][0]['total']),('Дом',20,30))
  self.assertEqual(row['total'],'30');self.assertEqual(row['amount'],'30')
  self.controls('bar','Сергей').click();self.assertEqual(self.drill()['ids'],['live','revived']);self.page.keyboard.press('Escape')
  self.select_view('circular');self.controls('legend','Сергей').click();self.assertEqual(self.drill()['ids'],['live','revived']);self.page.keyboard.press('Escape')

 def test_insights_follow_selected_month_year_and_all_time_with_deterministic_ties(self):
  result=self.evaluate('''
   state.entries=[{id:'dec',type:'expense',date:'2025-12-31',amount:40,category:'Дом',beneficiary:'Сергей'},
    {id:'jan-a',type:'expense',date:'2026-01-01',amount:10,category:'Продукты',beneficiary:'Сергей'},
    {id:'jan-b',type:'expense',date:'2026-01-31',amount:10,category:'Продукты',beneficiary:'Сергей'}];
   const monthField=document.getElementById('analyticsMonth');monthField.add(new Option('Январь','2026-01'));monthField.value='2026-01';renderAnalytics();const january=v185ParticipantCategoryInsights();
   document.getElementById('analyticsScope').value='all';renderAnalytics();const all=v185ParticipantCategoryInsights(),caption=document.getElementById('peopleChartHint').textContent;
   state.entries.reverse();renderAnalytics();return {january,all,reordered:v185ParticipantCategoryInsights(),caption};
  ''')
  self.assertEqual((result['january'][0]['categoryKey'],result['january'][0]['amount']),('Продукты',20))
  self.assertEqual((result['all'][0]['categoryKey'],result['all'][0]['amount'],result['all'][0]['total']),('Дом',40,60))
  self.assertEqual(result['all'],result['reordered']);self.assertIn('За всё время',result['caption'])

 def test_insights_empty_for_separate_directions_and_render_safe_labels(self):
  result=self.evaluate('''
   state.entries=[{id:'car-only',type:'expense',date:'2026-11-05',amount:40,category:'Бензин',beneficiary:'Сергей'}];renderAnalytics();const empty=v185ParticipantCategoryInsights(),emptyText=document.getElementById('v185ParticipantInsights').textContent;
   state.entries.push({id:'unsafe',type:'expense',date:'2026-11-05',amount:.01,category:'<img src=x onerror=alert(1)>',beneficiary:'<script>alert(1)</script>'});renderAnalytics();
   return {empty,emptyText,text:document.getElementById('v185ParticipantInsights').textContent,unsafe:document.querySelectorAll('#v185ParticipantInsights img,#v185ParticipantInsights script').length};
  ''')
  self.assertEqual(result['empty'],[]);self.assertIn('Нет расходов получателей',result['emptyText'])
  self.assertIn('<script>',result['text']);self.assertIn('<img',result['text']);self.assertEqual(result['unsafe'],0)
 def test_shop_category_columns_keep_all_rows_reachable_and_switch_to_stack(self):
  self.evaluate('''state.entries=Array.from({length:24},(_,i)=>({id:'column-'+i,type:'expense',date:'2026-11-05',amount:i+1,category:'Категория '+i,beneficiary:'Общее',store:'Магазин '+i}));state.entries.push({id:'prior-shop',type:'expense',date:'2026-10-05',amount:30,category:'Прошлый месяц',beneficiary:'Общее',store:'Прошлый магазин'});renderAnalytics();''')
  self.assertEqual(self.page.locator('#v163AnalyticsStoresList button').count(),24);self.assertEqual(self.page.locator('#aCatsDetails button').count(),24)
  self.assertEqual(self.page.locator('#v165CategoryTitle').inner_text(),'Общие расходы по категориям')
  for width in [320,390,600,768,820,980,1024,1280,1440,1920]:
   self.page.set_viewport_size({'width':width,'height':1000})
   data=self.evaluate('''const shops=document.getElementById('v163AnalyticsStores'),cats=document.getElementById('v165CategorySummary'),r=shops.getBoundingClientRect(),c=cats.getBoundingClientRect();return {shops:{x:r.x,y:r.y,width:r.width,height:r.height},cats:{x:c.x,y:c.y,width:c.width,height:c.height},cards:document.querySelectorAll('#v179AnalyticsBreakdowns>.card').length,overflow:document.documentElement.scrollWidth>document.documentElement.clientWidth+1,lists:[...document.querySelectorAll('#v163AnalyticsStoresList,#aCatsDetails')].map(e=>({height:e.clientHeight,scroll:e.scrollHeight,style:getComputedStyle(e).overflowY})),unique:['v163AnalyticsStores','v165CategorySummary','v176ParticipantDistribution'].every(id=>document.querySelectorAll('#'+id).length===1)};''')
   self.assertFalse(data['overflow'],width);self.assertEqual(data['cards'],2);self.assertTrue(data['unique']);self.assertEqual(len(data['lists']),2)
   for item in data['lists']:self.assertLessEqual(item['height'],570);self.assertGreater(item['scroll'],item['height']);self.assertEqual(item['style'],'auto')
   if width>980:
    self.assertLess(data['shops']['x'],data['cats']['x']);self.assertAlmostEqual(data['shops']['y'],data['cats']['y'],delta=1);self.assertAlmostEqual(data['shops']['width'],data['cats']['width'],delta=1);self.assertAlmostEqual(data['shops']['height'],data['cats']['height'],delta=1)
   else:self.assertLess(data['shops']['y'],data['cats']['y'])
  self.page.locator('#v163AnalyticsStoresList button').last.click();self.assertEqual(self.drill()['ids'],['column-0']);self.page.keyboard.press('Escape')
  self.page.locator('#aCatsDetails button').last.click();self.assertEqual(self.drill()['ids'],['column-0']);self.page.keyboard.press('Escape')
  self.evaluate("document.getElementById('analyticsScope').value='all';renderAnalytics();")
  self.assertEqual(self.page.locator('#v163AnalyticsStoresList button').count(),25);self.page.locator('#v163AnalyticsStoresList button').last.click();self.assertEqual(self.drill()['scope'],'all');self.assertEqual(self.drill()['ids'],['column-0'])

if __name__=='__main__':unittest.main(verbosity=2)
