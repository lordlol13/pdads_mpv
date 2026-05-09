from app.backend.services.llm_service import is_valid_news

samples = {
    "uz_latin": (
        "O'zbekistonda raqamli iqtisodiyot bo'yicha yangi dastur ishga tushirildi. "
        "Mutaxassislar bu tashabbus eksport salohiyatini oshirishini aytmoqda. "
        "Loyihada Samarqand va Toshkentdagi startaplar ham ishtirok etadi. "
        "Shuningdek, yoshlar uchun grantlar ajratilishi rejalashtirilgan. "
    ) * 3,
    "uz_cyrillic": (
        "Ўзбекистонда янги инвестиция дастури қабул қилинди. "
        "Лойиҳа доирасида ҳудудларда иш ўринлари яратилади ва инфратузилма янгиланади. "
        "Мутахассислар бу қарор иқтисодий ўсишни тезлаштиришини таъкидлади. "
    ) * 5,
    "mixed_uz_ru": (
        "Toshkentda IT-forum bo'lib o'tdi, эксперты обсудили стартап экотизими ва sun'iy intellekt yechimlari. "
        "Участники отметили, что hamkorlik va инвестиции ortmoqda. "
    ) * 6,
    "english": (
        "The government announced a new digital strategy for the region. "
        "The report highlights investment growth and innovation support across multiple sectors. "
        "Analysts said the market response was positive and international partners welcomed the reform package. "
    ) * 3,
}

for key, value in samples.items():
    print(key, is_valid_news(value))
