"""Treść zakładki „Jak sprzedawać w BUR” – lista kontrolna dla dostawcy szkoleń IT.

Zasady BUR i operatorów się zmieniają: przed decyzją zawsze sprawdź aktualny
Regulamin BUR oraz regulamin naboru konkretnego operatora.
"""

SEKCJE = [
    {
        "tytul": "1. Fundament: konto i Karta Dostawcy Usług",
        "punkty": [
            ("Konto dostawcy w BUR jest aktywne (logowanie przez login.gov.pl).", ""),
            ("Karta Dostawcy Usług jest kompletna i aktualna.",
             "Opis doświadczenia, zaplecze, dane kontaktowe, prawidłowe PKD. Operatorzy i klienci to czytają."),
            ("Masz ważne potwierdzenie jakości uznawane w BUR.",
             "Np. certyfikat/znak jakości z listy dopuszczonych w Regulaminie BUR. Pilnuj daty ważności – po jej upływie usługi znikają z oferty."),
            ("Zbierasz oceny uczestników po każdej usłudze.",
             "Średnia ocen jest publiczna i wpływa na wybór klienta. Przypominaj uczestnikom o ankiecie."),
        ],
    },
    {
        "tytul": "2. Karta Usługi, która przechodzi weryfikację operatora",
        "punkty": [
            ("Tytuł zawiera frazy, które wpisują klienci: „Excel”, „Power BI”, „SQL”, „analiza danych”.",
             "Klient szuka w wyszukiwarce BUR – ogólny tytuł „Szkolenie komputerowe” przegrywa."),
            ("Cel edukacyjny i efekty uczenia się są mierzalne (wiedza / umiejętności / kompetencje społeczne).",
             "Np. „Uczestnik tworzy model danych w Power BI z relacjami i miarami DAX”, a nie „pozna Power BI”."),
            ("Opisana walidacja efektów (test, zadanie praktyczne) i kto ją prowadzi.",
             "Wielu operatorów dofinansowuje wyłącznie usługi kończące się potwierdzeniem kompetencji lub kwalifikacji."),
            ("Rozważ ścieżkę z zewnętrznym certyfikatem (np. egzamin Microsoft PL-300, MOS Excel, ICDL).",
             "Część regionów preferuje usługi prowadzące do kwalifikacji lub rozwijające kompetencje cyfrowe – sprawdź regulamin naboru."),
            ("Harmonogram godzinowy jest szczegółowy, a rodzaj godzin (zegarowe/dydaktyczne) jasny.", ""),
            ("Forma zdalna = „zdalna w czasie rzeczywistym” z opisem platformy i weryfikacji obecności.", ""),
            ("Cena za osobogodzinę mieści się w realiach rynku i limitach operatora.",
             "Porównaj medianę w zakładce „Rynek w BUR” dla tematu i województwa. Operatorzy często mają maksymalną stawkę za godzinę."),
        ],
    },
    {
        "tytul": "3. Timing: sprzedawaj pod nabory",
        "punkty": [
            ("Masz listę operatorów z województw, w których są Twoi klienci.",
             "Lista operatorów jest w serwisie informacyjnym BUR (PARP). Dofinansowanie zwykle zależy od siedziby/oddziału firmy-klienta."),
            ("Znasz harmonogram naborów tych operatorów (zapisane strony, newslettery).", ""),
            ("Terminy usług publikujesz z wyprzedzeniem – tak, by klient zdążył podpisać umowę z operatorem i zapisać się z ID wsparcia.", ""),
            ("Masz kilka terminów i usługę zdalną, dostępną dla firm z wielu województw.", ""),
            ("Gdy otwiera się nabór, klienci dostają od Ciebie informację tego samego dnia.",
             "Środki w naborach potrafią się wyczerpać w kilka dni."),
        ],
    },
    {
        "tytul": "4. Sprzedaż aktywna – zgodnie z zasadami",
        "punkty": [
            ("Tłumaczysz klientowi proces: konto w BUR → wniosek do operatora → ID wsparcia → zapis na usługę.",
             "Wniosek składa i podpisuje przedsiębiorca – sprawdź, jaki udział dostawcy dopuszcza operator."),
            ("Nie oferujesz korzyści za wybór usługi (gratisy, zwrot wkładu własnego, rabat „za dofinansowanie”).",
             "To naruszenie Regulaminu BUR – grozi zawieszeniem konta i korektą dofinansowania."),
            ("Masz ścieżkę rozwojową: Excel → Power Query/Pivot → Power BI → SQL.",
             "Łatwiej sprzedać drugi i trzeci krok firmie, która już przeszła przez proces dofinansowania."),
            ("Raz w miesiącu sprawdzasz konkurencję (ceny, terminy, nowe usługi) w zakładce „Rynek w BUR”.", ""),
            ("Masz studia przypadków / referencje z branż, które kupują Twoje szkolenia.", ""),
        ],
    },
]

LINKI = [
    ("Baza Usług Rozwojowych – wyszukiwarka", "https://uslugirozwojowe.parp.gov.pl/"),
    ("Serwis informacyjny BUR (PARP) – aktualności, regulamin, lista operatorów", "https://serwis-uslugirozwojowe.parp.gov.pl/"),
    ("Dokumentacja API BUR", "https://uslugirozwojowe.parp.gov.pl/api/"),
    ("Regulamin korzystania z usługi API PARP", "https://www.parp.gov.pl/images/api/regulamin_korzystania_z_uslugi_api_parp_28062024.pdf"),
]
