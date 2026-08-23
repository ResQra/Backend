"""Seed the Guides table with flood preparedness / survival content.

Usage:
    python scripts/seed_guides.py        (run create_tables.py first)
"""

import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.db.repos import guides  # noqa: E402

NOW = int(time.time() * 1000)

GUIDES = [
    {
        "id": "g_before_01",
        "type": "article",
        "category": "before",
        "language": "en",
        "order": 1,
        "read_minutes": 4,
        "title": "Prepare Before the Flood Season",
        "summary": "A household plan made before the monsoon is the single biggest factor in how safely your family comes through a flood.",
        "body": (
            "Flooding in Bihar and along river basins is seasonal and predictable in timing, even when its severity is not. "
            "Preparation done in the dry months determines outcomes in the wet ones.\n\n"
            "Make a household plan. Agree on two meeting points — one near your home and one on higher ground — in case family "
            "members are separated when water rises. Every member, including children, should know these points and one "
            "out-of-area contact number to call, because local lines are often the first to fail.\n\n"
            "Waterproof what matters. Put Aadhaar cards, land documents, ration cards, school certificates and some cash in a "
            "sealed plastic pouch and keep it where you can grab it in seconds. Take photos of every document and store them "
            "on your phone and with a relative.\n\n"
            "Know your ground. Identify the nearest shelter and the route to it that stays passable longest. Routes along "
            "riverbanks and through low-lying lanes flood first; roads that lead to schools, colleges and elevated government "
            "buildings usually remain usable.\n\n"
            "Prepare the household kit. See our Emergency Kit Checklist for the full list. The essentials: three days of "
            "drinking water, dry food, a torch, a charged power bank, a whistle and a first-aid box.\n\n"
            "Watch official sources. During the season, check river levels and advisories on this app daily. When an advisory "
            "says move, move early — evacuation before water reaches your lane is safe; evacuation through moving water is not."
        ),
    },
    {
        "id": "g_kit_01",
        "type": "checklist",
        "category": "kit",
        "language": "en",
        "order": 2,
        "read_minutes": 3,
        "title": "Emergency Kit Checklist",
        "summary": "Everything your household needs for 72 hours of displacement, in one grab-and-go bag.",
        "items": [
            "Drinking water — 3 litres per person per day, for 3 days",
            "Dry food for 3 days (biscuits, chana, flattened rice, nuts)",
            "Torch with extra batteries",
            "Power bank, fully charged, with charging cable",
            "First-aid box: bandages, antiseptic, ORS packets, fever medicine",
            "Whistle — to signal rescuers without exhausting your voice",
            "Copies of ID and land documents in a sealed waterproof pouch",
            "Cash in small notes (ATMs and digital payment fail in floods)",
            "Regular medicines for 7 days, especially for elderly and children",
            "Baby supplies if needed: milk powder, feeding bottle, diapers",
            "One change of clothes per person, wrapped in plastic",
            "Matchbox or lighter in a waterproof container",
            "Rope (10 metres) and a sturdy stick for checking depth",
        ],
    },
    {
        "id": "g_during_01",
        "type": "article",
        "category": "during",
        "language": "en",
        "order": 3,
        "read_minutes": 4,
        "title": "When Water Enters Your Home",
        "summary": "The first thirty minutes decide your safety. Act in this order: electricity, elevation, communication.",
        "body": (
            "The moment water crosses your threshold, you are no longer protecting a house — you are protecting the people in it. "
            "Act in a fixed order and do not improvise.\n\n"
            "Cut the electricity first. Switch off the main breaker before water reaches plug points. Electrocution is one of "
            "the most common flood deaths inside homes, and it is entirely preventable. Do not touch any switch, appliance or "
            "board while standing in water.\n\n"
            "Move up, not out. Go to the highest floor or the rooftop with your kit, documents and phone. Take bright cloth — "
            "a sari, a towel, anything visible — to signal with. Do not wait on the ground floor to 'see how bad it gets'; "
            "water that is ankle-deep at the door can be chest-deep within the hour.\n\n"
            "Communicate deliberately. Send one clear message with your exact location and the number of people with you — "
            "through this app's SOS or chat. Then conserve battery: lower screen brightness, close background apps, switch to "
            "airplane mode between check-ins.\n\n"
            "Never enter moving water. Fifteen centimetres of moving water can knock an adult down; sixty centimetres can "
            "sweep away a car. Do not wade to 'check' the street, and do not attempt to drive through flooded underpasses.\n\n"
            "Drink only stored or boiled water. Flood water carries sewage, and the diseases it causes — diarrhoea, "
            "leptospirosis, typhoid — arrive days after the water and are often deadlier. Keep ORS ready and use it at the "
            "first sign of loose motions, especially in children."
        ),
    },
    {
        "id": "g_during_02",
        "type": "article",
        "category": "during",
        "language": "en",
        "order": 4,
        "read_minutes": 3,
        "title": "Stranded on a Rooftop: Staying Safe Until Help Arrives",
        "summary": "How to stay visible, dry and communicative — and what not to do — while waiting for a rescue boat.",
        "body": (
            "Being on a rooftop is a good outcome; most rooftop rescues in Patna's floods are completed within hours. Your job "
            "is to remain findable and stable until the boat reaches you.\n\n"
            "Be visible. Spread a bright cloth where it can be seen from a distance and from the air. When a boat or "
            "helicopter approaches, wave it slowly and widely — frantic small movements are harder to spot than large slow ones.\n\n"
            "Stay dry and warm. Wet clothes drain body heat even in warm weather, and children and the elderly lose it "
            "fastest. Sit on your bag or a plank rather than directly on wet concrete; wrap children in the driest cloth "
            "available.\n\n"
            "Ration your phone. One check-in message every hour is enough. If the network is weak, try SMS — it often "
            "delivers when calls and data fail.\n\n"
            "Do not attempt to swim to safety unless you are in immediate physical danger where you are. Distance over water "
            "is deceptive, submerged obstacles are invisible, and currents near flooded streets are strongest at bridges and "
            "drains. Boats recover people from rooftops every single time; they cannot recover people who left the rooftop.\n\n"
            "Signal with sound only when it matters. Three short whistle blasts at intervals is the universally understood "
            "distress signal and costs far less energy than shouting."
        ),
    },
    {
        "id": "g_health_01",
        "type": "article",
        "category": "health",
        "language": "en",
        "order": 5,
        "read_minutes": 4,
        "title": "Flood Water and Your Health",
        "summary": "Flood water is sewage. Protect wounds, feet and drinking water, and know the warning signs that need a doctor.",
        "body": (
            "Every flood carries a second emergency behind it: infection. The water pooling in streets and homes mixes sewage, "
            "chemicals and animal waste. Treat all of it as contaminated.\n\n"
            "Cover every wound. Any cut or scratch that touches flood water must be washed immediately with clean water and "
            "soap and covered waterproof. Open wounds in flood water can lead to leptospirosis and severe bacterial "
            "infections within days. If a wound turns red, swells or throbs, get to a medical camp — do not wait.\n\n"
            "Never walk barefoot. Broken glass, nails and sharp metal lie invisible under the waterline. Rubber chappals or "
            "boots, tied to your bag when not in use, are some of the most valuable items you can carry.\n\n"
            "Water discipline. Drink only sealed, boiled or properly stored water. Wash hands with soap before eating and "
            "after any contact with flood water — this single habit prevents the majority of flood-season diarrhoea.\n\n"
            "Watch for these signs and seek a doctor or medical camp urgently: high fever with body ache after wading through "
            "water (possible leptospirosis), loose stools more than three times a day, vomiting, or reduced and dark urine "
            "(dehydration). Start ORS early in anyone with diarrhoea — children first.\n\n"
            "Mosquitoes follow floods. Water that stands for a week breeds dengue and malaria vectors. Use repellent or "
            "full-sleeve clothing at dusk, especially for children, and report fever with rash immediately."
        ),
    },
    {
        "id": "g_after_01",
        "type": "article",
        "category": "after",
        "language": "en",
        "order": 6,
        "read_minutes": 4,
        "title": "Returning Home After the Flood",
        "summary": "Re-enter in the right order — structure, electricity, water, food — and document damage before cleaning it.",
        "body": (
            "The water leaving your home is not the end of the emergency; the order in which you re-occupy it decides whether "
            "it stays safe.\n\n"
            "Structural safety first. If walls absorbed water for more than a day, look for new cracks, bulges or a soft "
            "floor before entering fully. Local authorities assess and mark damaged buildings after every major flood — "
            "respect those markings.\n\n"
            "Electricity second. Do not switch the mains on yourself. Let an electrician or the supply team inspect sockets "
            "and wiring that were submerged, and stand on dry ground with rubber slippers for any interaction with the board.\n\n"
            "Water and food discipline continues. Assume the well and hand pump are contaminated until they are chlorinated "
            "— boil or use supplied water. Discard any food, grain or medicine that touched water, including sealed packets "
            "that were submerged; the seals do not survive pressure and silt.\n\n"
            "Document before you clean. Photograph every damaged item, wall and document while it is still visibly damaged — "
            "compensation and insurance claims run on this evidence. Then clean with disinfectant or hot water, and dry the "
            "house fully over several days to prevent mould, which triggers asthma especially in children.\n\n"
            "Watch health for two more weeks. Fever, jaundice-eyes, or body ache after wading still need a medical camp — "
            "post-flood disease outbreaks peak in the second week, when everyone has stopped being careful."
        ),
    },
    {
        "id": "g_health_02",
        "type": "article",
        "category": "health",
        "language": "en",
        "order": 7,
        "read_minutes": 3,
        "title": "Protecting Children and the Elderly",
        "summary": "The two groups who suffer most in displacement — and the small routines that keep them stable.",
        "body": (
            "Children and the elderly do not experience floods as an event; they experience them as the loss of routine. "
            "Restoring small routines is protective, not a luxury.\n\n"
            "For children: keep to regular meal and sleep times as far as possible, even in a shelter. Answer their questions "
            "honestly but calmly — a composed adult is the strongest signal of safety a child can receive. Watch quiet "
            "children more than crying ones; withdrawal and repeated play acting out the flood are normal for a few weeks, "
            "but persistent sleep problems or refusal to eat deserve attention. Never let children play near or in flood "
            "water, even shallow edges — this is when most child drownings and infections happen.\n\n"
            "For the elderly: list their medicines and doses on paper now, before any emergency, with a photo on your phone. "
            "In shelters and on rooftops, elderly people dehydrate and lose body heat faster than you expect — offer water "
            "regularly even when they do not ask, and keep a dry layer of clothing for them specifically. People with "
            "diabetes, heart conditions or dialysis needs should be evacuated earlier than others, not with the general "
            "population — their condition can deteriorate faster than the water rises.\n\n"
            "Keep one familiar object for each — a child's toy, an elder's walking stick or spectacles. In displacement, "
            "continuity of small things anchors people more than we assume."
        ),
    },
    {
        "id": "g_before_01_hi",
        "type": "article",
        "category": "before",
        "language": "hi",
        "order": 8,
        "read_minutes": 3,
        "title": "बाढ़ के मौसम से पहले की तैयारी",
        "summary": "सूखे मौसम में बनाई गई योजना ही बाढ़ में आपके परिवार की सुरक्षा तय करती है।",
        "body": (
            "बाढ़ कब आएगी, यह तय नहीं हो सकता, लेकिन यह मौसम के साथ आती है — इसलिए पहले से तैयारी संभव है।\n\n"
            "घर की योजना बनाएं। दो मिलने की जगह तय करें — एक घर के पास, एक ऊँची जगह पर। परिवार के हर सदस्य को, "
            "बच्चों समेत, ये जगहें और एक बाहरी फोन नंबर याद होना चाहिए, क्योंकि स्थानीय नेटवर्क सबसे पहले बंद होते हैं।\n\n"
            "कागज़ात जलरोधक बनाएं। आधार कार्ड, ज़मीन के दस्तावेज़, राशन कार्ड और कुछ नकद पैसा सीलबंद प्लास्टिक में रखें, "
            "ऐसी जगह जहाँ से तुरंत उठा सकें। हर दस्तावेज़ की फोटो फोन में और किसी रिश्तेदार के पास रखें।\n\n"
            "अपने इलाके को जानें। सबसे नज़दीकी आश्रय और वह रास्ता पहचानें जो सबसे देर तक चलने योग्य रहता है — आमतौर पर "
            "स्कूल, कॉलेज और ऊँची सरकारी इमारतों वाले रास्ते।\n\n"
            "आपातकालीन थैली तैयार रखें — पीने का पानी, सूखा खाना, टॉर्च, चार्ज़्ड पावर बैंक, सीटी और प्राथमिक चिकित्सा बॉक्स। "
            "पूरी सूची के लिए 'Emergency Kit Checklist' देखें।\n\n"
            "सरकारी सलाह पर नज़र रखें। जब भी सलाह आए कि हटें, जल्दी हटें — पानी गली में आने से पहले निकलना सुरक्षित है, "
            "बहते पानी में निकलना नहीं।"
        ),
    },
    {
        "id": "g_during_01_hi",
        "type": "article",
        "category": "during",
        "language": "hi",
        "order": 9,
        "read_minutes": 3,
        "title": "घर में पानी आने पर क्या करें",
        "summary": "पहले तीस मिनट तय करते हैं सुरक्षा — इस क्रम में काम करें: बिजली, ऊँचाई, संपर्क।",
        "body": (
            "पानी घर में आते ही घर बचाना नहीं, लोग बचाना मकसद बन जाता है। तय क्रम में काम करें।\n\n"
            "सबसे पहले बिजली बंद करें। मेन स्विच ऑफ करें, पानी सॉकेट तक पहुँचने से पहले। पानी में खड़े होकर किसी स्विच "
            "या उपकरण को हाथ न लगाएं — घर के अंदर बाढ़ से मौत का सबसे आम कारण बिजली का करंट है।\n\n"
            "बाहर नहीं, ऊपर जाएं। अपनी थैली, दस्तावेज़ और फोन लेकर सबसे ऊँची मंज़िल या छत पर जाएं। एक चमकीला कपड़ा साथ "
            "लें — संकेत देने के लिए। 'देखें कितना बढ़ता है' कहकर नीचे इंतज़ार न करें।\n\n"
            "एक साफ संदेश भेजें — अपनी सटीक जगह और साथ के लोगों की संख्या के साथ — इस ऐप के SOS या चैट से। फिर फोन की "
            "बैटरी बचाएं: स्क्रीन की रोशनी कम करें, बैकग्राउंड ऐप बंद करें।\n\n"
            "बहते पानी में कभी न उतरें। पंद्रह सेंटीमीटर बहता पानी वयस्क को गिरा सकता है और साठ सेंटीमीटर गाड़ी बहा सकता है। "
            "सड़क 'देखने' न जाएं और डूबे फ्लाईओवर-अंडरपास से गाड़ी न निकालें।\n\n"
            "केवल बंद या उबाला पानी पिएं। बाढ़ का पानी गंदगी ले चलता है — दस्त, लेप्टोस्पाइरोसिस और टाइफाइड जल के जाने के "
            "बाद आते हैं। ORS तैयार रखें और बच्चों में दस्त के पहले लक्षण पर शुरू करें।"
        ),
    },
    {
        "id": "g_after_01_hi",
        "type": "article",
        "category": "after",
        "language": "hi",
        "order": 10,
        "read_minutes": 3,
        "title": "बाढ़ के बाद घर लौटते समय की सावधानियां",
        "summary": "सही क्रम में घर में लौटें — ढाँचा, बिजली, पानी, खाना — और सफाई से पहले नुकसान के प्रमाण जुटाएं।",
        "body": (
            "पानी का जाना आपातकाल का अंत नहीं है; लौटने का क्रम तय करता है कि घर सुरक्षित रहेगा या नहीं।\n\n"
            "पहले ढाँचा जाँचें। एक दिन से ज़्यादा पानी में रही दीवारों पर नई दरार या उभार है तो पूरा अंदर जाने से पहले "
            "सोचें। प्रशासन की लगाई खतरे की मुहर का सम्मान करें।\n\n"
            "फिर बिजली। मेन स्विच खुद ऑफ या ऑन न करें — डूबे सॉकेट और तार बिजली मिस्त्री या विभाग से जाँचवाएं।\n\n"
            "पानी-खाने की पाबंदी जारी रखें। कुएं और हैंडपंप को क्लोरीनयुक्त होने तक दूषित मानें — पानी उबालकर या "
            "आपूर्ति वाला पिएं। पानी लगा कोई खाना, अनाज या दवाई फेंक दें — सीलबंद पैकेट भी, अगर डूबे थे।\n\n"
            "सफाई से पहले प्रमाण। ज़िदगी का हर नुकसान — दीवार, सामान, दस्तावेज़ — की फोटो तब लें जब वह दिख रहा हो; "
            "मुआवज़े के दावे इसी सबूत पर चलते हैं। फिर डिसइन्फेक्टेंट से सफाई करें और घर को कई दिन अच्छी तरह सुखाएं।\n\n"
            "दो हफ्ते तक सेहत पर नज़र रखें। पानी में चलने के बाद बुखार, पीली आँखें या शरीर दर्द हो तो चिकित्सा शिविर "
            "ज़रूर जाएं — बाढ़ के बाद बीमारियाँ दूसरे हफ्ते चरम पर होती हैं।"
        ),
    },
]


def main() -> None:
    for g in GUIDES:
        item = {k: v for k, v in g.items() if v is not None}
        item["updated_at"] = NOW
        guides.put_guide(item)
        print(f"+ guide {g['id']} ({g['language']}) — {g['title']}")
    print(f"done — {len(GUIDES)} guides seeded")


if __name__ == "__main__":
    main()
