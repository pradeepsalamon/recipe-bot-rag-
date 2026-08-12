# Ask My Recipes - Evaluation Results

## 1. Eight Evaluation Questions

**Question:** How much salt is used in the Idli recipe?
- **Known correct recipe:** idli
- **Known correct section:** Ingredients
- **Expected answer:** 15 g

**Question:** What is the ratio % of Urad dal in the Dosa recipe?
- **Known correct recipe:** dosa
- **Known correct section:** Ingredients
- **Expected answer:** 33%

**Question:** How many cashews are needed for Ven Pongal?
- **Known correct recipe:** ven_pongal
- **Known correct section:** Ingredients
- **Expected answer:** 30 g

**Question:** How long should the Idli batter ferment?
- **Known correct recipe:** idli
- **Known correct section:** Method
- **Expected answer:** 8-12 hours

**Question:** What is the first step in making Ven Pongal?
- **Known correct recipe:** ven_pongal
- **Known correct section:** Method
- **Expected answer:** Dry roast moong dal lightly until fragrant

**Question:** How long should the Sambar simmer after adding the tamarind pulp?
- **Known correct recipe:** sambar
- **Known correct section:** Method
- **Expected answer:** 10 minutes

**Question:** What is the yield for the Rasam recipe?
- **Known correct recipe:** rasam
- **Known correct section:** Meta
- **Expected answer:** 4 servings

**Question:** Why should Rasam only froth slightly when ready?
- **Known correct recipe:** rasam
- **Known correct section:** Notes
- **Expected answer:** preserves its flavor (simmered not boiled)

## 2. Chunking Comparison

| Question | Current Chunker (Baseline) | Structure-Aware |
|----------|----------------------------|-----------------|
| Q1 | Hit | Hit |
| Q2 | Hit | Hit |
| Q3 | Hit | Hit |
| Q4 | Hit | Hit |
| Q5 | Miss | Miss |
| Q6 | Hit | Hit |
| Q7 | Miss | Miss |
| Q8 | Hit | Hit |

**Current chunker:** 6/8
**Structure-aware chunker:** 6/8

### Detailed Top-5 Search Results (Structure-Aware)

**Q1**: How much salt is used in the Idli recipe?
  1. Recipe: idli, Score: 0.689, Chunk: chunk_cde47aaa
  2. Recipe: idli, Score: 0.497, Chunk: chunk_cf0e597b
  3. Recipe: idli, Score: 0.494, Chunk: chunk_a515bd88
  4. Recipe: idli, Score: 0.493, Chunk: chunk_8a115db7
  5. Recipe: idli, Score: 0.484, Chunk: chunk_8a4b7501

**Q2**: What is the ratio % of Urad dal in the Dosa recipe?
  1. Recipe: dosa, Score: 0.728, Chunk: chunk_3e14d0f5
  2. Recipe: dosa, Score: 0.590, Chunk: chunk_e8e56705
  3. Recipe: dosa, Score: 0.588, Chunk: chunk_51a1c54b
  4. Recipe: dosa, Score: 0.578, Chunk: chunk_418c6419
  5. Recipe: dosa, Score: 0.567, Chunk: chunk_2074ad5b

**Q3**: How many cashews are needed for Ven Pongal?
  1. Recipe: ven_pongal, Score: 0.559, Chunk: chunk_7b726153
  2. Recipe: ven_pongal, Score: 0.558, Chunk: chunk_0df1a3f4
  3. Recipe: ven_pongal, Score: 0.505, Chunk: chunk_f97ed4c6
  4. Recipe: ven_pongal, Score: 0.399, Chunk: chunk_9f569565
  5. Recipe: ven_pongal, Score: 0.393, Chunk: chunk_f6b6eec1

**Q4**: How long should the Idli batter ferment?
  1. Recipe: idli, Score: 0.663, Chunk: chunk_5ac0b6a4
  2. Recipe: dosa, Score: 0.498, Chunk: chunk_d749aa1e
  3. Recipe: idli, Score: 0.405, Chunk: chunk_9ea03312
  4. Recipe: idli, Score: 0.402, Chunk: chunk_836ac807
  5. Recipe: idli, Score: 0.337, Chunk: chunk_8a115db7

**Q5**: What is the first step in making Ven Pongal?
  1. Recipe: ven_pongal, Score: 0.698, Chunk: chunk_8b5a14d9
  2. Recipe: ven_pongal, Score: 0.683, Chunk: chunk_9f569565
  3. Recipe: ven_pongal, Score: 0.619, Chunk: chunk_0df1a3f4
  4. Recipe: ven_pongal, Score: 0.600, Chunk: chunk_f97ed4c6
  5. Recipe: ven_pongal, Score: 0.565, Chunk: chunk_9ab57eaa

**Q6**: How long should the Sambar simmer after adding the tamarind pulp?
  1. Recipe: sambar, Score: 0.574, Chunk: chunk_d6fbc2ec
  2. Recipe: sambar, Score: 0.362, Chunk: chunk_0f691769
  3. Recipe: rasam, Score: 0.347, Chunk: chunk_1fbe81fa
  4. Recipe: sambar, Score: 0.335, Chunk: chunk_e3bfec74
  5. Recipe: sambar, Score: 0.276, Chunk: chunk_74c1cbd0

**Q7**: What is the yield for the Rasam recipe?
  1. Recipe: rasam, Score: 0.537, Chunk: chunk_850c1019
  2. Recipe: rasam, Score: 0.509, Chunk: chunk_c388e6a5
  3. Recipe: rasam, Score: 0.496, Chunk: chunk_e5d73d96
  4. Recipe: rasam, Score: 0.495, Chunk: chunk_f16abe83
  5. Recipe: rasam, Score: 0.490, Chunk: chunk_b9862ae4

**Q8**: Why should Rasam only froth slightly when ready?
  1. Recipe: rasam, Score: 0.701, Chunk: chunk_e5789868
  2. Recipe: rasam, Score: 0.315, Chunk: chunk_1747994c
  3. Recipe: rasam, Score: 0.295, Chunk: chunk_b9862ae4
  4. Recipe: rasam, Score: 0.221, Chunk: chunk_217d25f9
  5. Recipe: rasam, Score: 0.220, Chunk: chunk_1fbe81fa

## 3. Metadata Filtering

**Query:** How do I make Ven Pongal?

**Unfiltered results (Top 3)**
- chunk_id: chunk_8b5a14d9 | score: 0.741 | recipe: ven_pongal
- chunk_id: chunk_9f569565 | score: 0.733 | recipe: ven_pongal
- chunk_id: chunk_f97ed4c6 | score: 0.612 | recipe: ven_pongal

**Filtered results (Dietary Tags contains 'Vegan') (Top 3)**

*Notice how Ven Pongal is excluded in the filtered results because it is not Vegan.*

## 4. Grounded Generation

**Question:** How much salt is used in the Idli recipe?
**Answer:** [{'type': 'text', 'text': 'The Idli recipe uses 15 g of salt. [chunk_cde47aaa]', 'extras': {'signature': 'Eq8ICqwIARFNMg+k6wRD5pza4cy/IaBx8hH8f838sIVUvtv60bGI84LNgecnW/9iYnxuqiJZS/F0HDKLPQ/bUHTAkIFi4LuqiPbtqX/GXi4IEBAWYkKIazGZ/dT4RwXaw4kUnDN8dPjyrbEXoMF/QkgfNBffZHoAllD4zTP35wneIccanA2ks6DPIdoZ6qikaVFcMYZNSmDfkA7+YWnvnd56HKc6gOJmyIHp+cYajEF+K4rO+6nEltShij/R0P6XabLfekLc2i+gQ33AdTYe3AgEmY1cDv8QLJ8nE67YAn1nyEPD7kD/p6Bi5AOXr2Y5gYonPJsxCKuCjqX0CoXYfAOT/zXhNRkYs2i/ZhU4nHqJXKTfu8yQpOhWgU+zW12aOjFRso0J6sHB2rAVCp81oUAjeej1eGFhqKqF3kN+Gd/FzcKHlr0FRgHNDmRFdEY5YMu8rrvtW5oxKTlVN+VvSKhzW/DBvwTyJxhYMze2M9IXlVgvqZoorCrubZLdNBgLqWVgu6bqqNNkchVzrx3YPy2Q1VAINY9ZgjSOffjk5JzfzRMVB0+Tz1ageCYDqEjys92kBB5vrOBnq/y448pRx+F0drDU8vb+/nK1nkJ5XQVII8WhRlLfMmXQEsvlzNTxfUQQQqniZVCtWiWMFc0liFnQs9ptcZQzyXirFjGfkfuNmp/v82hDUMpyOeC3h5EjEYxkhShAYo9GDDSjIfYFN0MoQY21tnPHN0KLIVw1Cefubhng23FLL4M3Gos4IyXrNHH4AHUQC0ZQ/71yLSUdPnqUNsEvyqzQbCi/rJ3Bnu2+QpLsQw7AZrZCUfXaU3iL4mIkXs412dkn/e52jtozjhEqSizRIlz3WhBytIVkMA5BqRp2/O8gAGH2Z4fernmMneOr4OCfW5tXxfFHRGdTNYjZqvkmQEeZKMYSTz9G8+QxF1HYju97lv6kNAf3nF7FvON9xscpfM1ZfRYL1pdarHqBAI9UV7kx9Xp7HS2U18laAGeajmZBqgB8l+Qvi4wJRAVMDUFcwmnc6XJtfo2DxwjALvBEMo3pzvfEh+OuMFuaVsUDBnBH7XYH5+o1s525U0VEy8zSHeH87yjTWw39ZDMU2vE5lGBM5PTZ4EO1V+R68So7v6+owe3v+rx2fEXez7eSyo+FTOk+mnQF+00QtLrNnmqbrNwGBw+yYnJ8+uK6k5hICPxNOfG4HDqNqyBi5Cw+RNghREFdSbecusXnPgTMWZcteF/TB/dGdijo/AUsla6nSpAH4kB6zsLfhwphkaUhLLyi715GjnKERY+v+KDydyxkKX3cG+afgpFb5+EQckusITaFvbVFi4gJrtDEwtRj0UriU1a6AxPZ6L38e+DdIXJ13+96gTqBp4yRVWh0c1QhMcpqiZHo8EuG+CNgXPwfJ3x2kMT9Zg4XbFu+S2Yc'}}]

**Context Chunks Used:**
- chunk_cde47aaa (idli)
- chunk_cf0e597b (idli)
- chunk_a515bd88 (idli)

**Question:** What is the ratio % of Urad dal in the Dosa recipe?
**Answer:** [{'type': 'text', 'text': 'The ratio % of Urad dal in the Dosa recipe is 33%. [chunk_3e14d0f5]', 'extras': {'signature': 'Eq0JCqoJARFNMg/fSDkMcVs2pp49IBoRGJ91/jnOGxtT1Oo8U0yBGiO0Wt/kPEsmerWJsuHhmbyGIvBuFCt9NXrs95SS6k38S6KTwHrVcsk57Nyhnpnzno3elKqxu3AVXUTcPCmVAvA/YcxhwskMy1/UWL2EboD/ldfprhZz66QOVyaUZpEAr+9y1yWMFVhchEp/8liqCLP0dxRUqzitWe0RHZWIkzvAy8oZC5GXeNmdvhk9nE8xRL3dPYhAuzxpw+ll3zKK5OgIpfnhknvbrPjlOILa/QQlA2gaSYhK9QyjLwkV9Rk5H28FpRZnp+snS4XD9cTy4m+ERbapiaTJuCCentJnEARMBNxUoL0CVdlOpSZCdI1488GbBBlcQKhDkflwRXQ1SF+wR9uWeSqM0Oj5qq4Gj3BpEE5AzqrzDUn+7C56FIq6zZ0bhSiWflVtipbpZcmLglhiEYN0rw31+6EgcN55b52LQotzIQSHaC1cDWWQZX1kEO+2bSI+7BMCgxSFPg7ctv5fb0P3qb0PY2rkbiTpDHVqlZcE8reokX073azhziG1uGLsUNsKj+jsche52q06LwAo+JUOCfJjj/34U6ULXPJsftH3/5DoDtEbysURuM0OR8J0hQBTxM5oWLyiK+lkWTJ4aao99AI2IqIUkQP+91zetUANqwqyOHWJIsq+6/ROxJbz4RhS5PVT9+IRZD7NVmWxHLbKJOPse2Gea/SWqAxcWIG9cUD63vnJzeo9meFf0X7Xw8sUhPPJB+CKHRMQuSd/g/ghUD3vlkU1/nsHSDtTWL4vruacnloLweQ53BCVYqkkJfTfhQOARQiN8K2opoRKl3Gxl43oqg9cPm1Sdcmb1MYz/BgQ2afIAumf2djN61vBhxxW/UYGNH1gRQy3Bg7MpS3deC1dGF5vHFDcnlSuBGkfz5+eEahov+xPQ4QfIYMkJFsiMIuJxTnlVNluPVJw2iHxto/MuULvvav5HN1VDQXq056qwphtPjxC9Ak/v+MiRnYsRBh3jE51/SG0eQGQhgYv+Vc04j+RQVfDQ0oLMD/FQLpFYGU4aeQS4ddrwk0lvaCOQz8zB2us7J0B9h43eNYOlYPqa1tsGSJnKIh4CIPuatyUPZg3aAu8sLcBdQIvJQeWtDla6FuK/qU5WgNDjdXJAKmEsZcNVDYJ76cLhsgQ8+wu82aUqSEVfQB51ZD7MVum1Vq9RrTRoG2F4JxQ5yc5nCr5ETtBWg3RPV4nAxw8ZfJ/yWJOPOA/zVk7H5FOh04o82cPZwZpL7qkUj+vM+C4Y55BGBxx0HW2m6EsU/2aINCysYAoj6A6hjAk7GaJEkxNOkyukBFFlVweHAfthy/Cro5h59oKg202KSvDrcCpLLUa9CM0vgHctrRkg/gS4cf5PALu4NfWiISuCzCvodo6wF83Xwt5SaLILGlMYeyUk0DTzWnG2982Wm6dOV8wibHZKYmy/1x0d8EayQzppkwUae8qyRGShH/pkJAYevyMmB3SOSGfYMmy/91EmrNdIv28htWsGJhiURTYuWu9UACLLwblUTK1zhdMMKt+XKn3QIV0p1wpOO35rORpekdyR0QToUZS'}}]

**Context Chunks Used:**
- chunk_3e14d0f5 (dosa)
- chunk_e8e56705 (dosa)
- chunk_51a1c54b (dosa)

**Question:** How many cashews are needed for Ven Pongal?
**Answer:** [{'type': 'text', 'text': 'For Ven Pongal, 30 g of cashews are needed. [chunk_7b726153]', 'extras': {'signature': 'EpsKCpgKARFNMg8DCyzRnM16J3qxuRGtjtjHE9BQivcIkm5trq9dHG9yGGyA2HgpdGN31wjmrie30jwsdLKc5gy8HKvUCknXk4zYCwMRQZUzgo5HFxUYrouQDavFQ7XC5iwdE+WRRU566NOD6YLTcCykW/oS1Ln270pUdSfOyHyVA0JK3tucl3OKYqA6c1n0zkdtHIuZQnLAzOhGFFUfY3z4i8OSAh8N7RVdQWnPGvXccqsBSZ/fOH0t4HCAfhUepWVpnNKmQnsnbW4Op5GYO8Ao0Zy8o3mqN9BIB9/FdFBqpwQqnkI45SPf7RPerS7/3QLJlTR/ILU7YPpbHliXhMRYeAdtlOAVvyjDAzDHgz4jgwCVtiNWgG52XmMda0RKre+1+rnXlC+Cd9BPTI/35ZuTFo+pXxqX1+fW9thAf117cGYlNZ6xGeT56OWwP66b9SZT+TXH97OmuCihkt4hS5Wokqp2e222SqjdcHgSmaJzLrKouP2UkQ4T28gkZaMCNHphF9WkJtLEOH7xvgpx9RclC7M+vxh7spK0qVlxYpoMH1uXucm/WPNncoozBuojPESiviMrP2M4IZaZaCtm3vA3GHXoVLt2rW951A6N5shwKcpYqmo5ZoiJcRMywRnhKyatEuwDXNnIhvDHiK6OcR2z2HX9RVsMXbDTMqThIL+9sydWCnk5P19TQ/cZANXlYJti/JMFEoVKE3d25KtegonVyqj1Vi2vPwaF2odsrSLD0OHeC1MAMRlnWg5j6BwBd/1NzZLicL35+WaOkSfpBq4rCVK0eSgtt4L7+HmFRZz6nIz0KkfgdmVV4sOPuxRbMkiPwGzWbHBzzwwAJNN/YdpvWkeiWkjdzmZONfTRR8vI1toT9N+2Wzqa7A6b2WRo4bqhWxc2CKb/sL1IM0e9odtwVF8mBjQnvyLW0voDGcsUixHEOGiOA2sp49lUEsxE2mT/q/bJIco6zm2e5CbbaLEAmiMhjSnKPKaksNHESUTxs/mnoWpc9cJ2yZ7pD+E9T8n8WjK/AXp4OSsmdwMddwez6yXuup/TtPHWuYZDJdQ9Y8yCxbUhTA00OU2G43H4ZYuwY3jflqmwLRsQ4/06wXT8tVcVB3cTYzLWCoRhhhOdq0TDfEoRvtLwz6GkekuDZ18i0rWpzL2ZXG4c3cQ5BMJqWIwgTvNnHsOkt5mkw3jRda373l8d4GgVumVe1YEE/rgP9H6IFYyya1W0YDV4qjhh5ysnSGAcXtQrhd5cFi4ELSWarPRGLsJNdB/AKaJ67p5uvRKeWqOriMZ6Rs2f+uEU3tplAREqgzrSgSGVIuJnNRoEsjJge4sYkhucaNK2SfFJbU8Ykq0olhkBMzo0Z8KWUbptpjWIlDvU6SyCQLsTea1VG/zlw0nYi8uCrgYEG3vMmIK7sM3Tta398eRRKH+mBJVHaYvfE3sFLQ1tlnTLPlryzVpGTX/juEPEVfcIYJwOYZsFLHjksi5Hm/0BzbMfbyTtSrUlcuRnUxLH/sVDAHONi2rlEqcHMQtxNb14FkoUADs2vBCObM7sIFGWqhIMv2VRMDP9gpibVOdIgLuCT35jitvr7vGknsRRzpfXsOu1r1YavdlWT7ZvLmQY3rz3smYgLWULuQ49e2wam9exuC9/PJy8FLmo40Mrf3saHgUZwShVbawqJr509uGOLqmQuUVsDa6RbTQsFR86+tmwp4EBeNIdYLvUzKevIlFWwfGbe+EzJ6f2AGZuK8I='}}]

**Context Chunks Used:**
- chunk_7b726153 (ven_pongal)
- chunk_0df1a3f4 (ven_pongal)
- chunk_f97ed4c6 (ven_pongal)

## 5. Refusal Transcripts

**Question:** What is the exact calorie count of the Idli recipe?
**Response:** [{'type': 'text', 'text': 'The information is not available in the provided recipe documents.', 'extras': {'signature': 'EpoJCpcJARFNMg+4Hmv6JnHFICoQ6s/WlpG6793EroIcftar0P129jorl9gxjvPFrs68u4NzDvGp9lMNZwyg0dkklPS3CG1Bx9fToaZIYBCwk21t7OqYxhkh4qJCsoinAgcDmA+5sfmp+fUEZ4bF/+4ijqAM5y6L3DrUlFZUF8/7suQ536t4QifmrD0ft/n50dfuRv3sVnp0/H6s/mLWBM6x+qTut2gvVXyu3PjqVoGhYvLpL1XPPjmV8vRqZIEJmVfRIWbdIuqaYMWGvX+jDLWVDSD8lsjeBOkJV2EUsVxzgtbiwwKLC3/4VZOXHKgqaFTp0/wF0WDTnXqyYwQqpQVw3dKOsZNCnCzbrhMbcwMI0YGGWU6WLoAhIJbcF0mOBseOiVyFdJz38xgbIvX6J+CJGQXgS1a5YnJEtcj+ej2itcoO1hrgaaOMqMO81nXsyw7w8dJkJc+0BnTi3TCvlGx8jrpNEaoFDOKfcgVrdPNJHgTswn6Bv+hMqXpCJfQaExCrdYIQEHkQbD4/08JY4Dyp/Wb4P3Hbh2kbzmngMDhHH9zWSmcubICVALtrcNXFcGdGGftr1XlpTZcnKzNjHvmrE69ORILb22eJ0A4hi6j/ZflQg59ODw3mdUIUU3DwsG+bnmXcmXViPR4hu6NNgpfAYTZKE26EJMnOSeuHW/S8WLYHNwnSZ8sWBFdfDs6aw1S8f42yYTINh3UFSUnoo40ObHq2mLI13ZmExwvyOBdx+fn0bnb7OrD4hIs9HRRoHZ3ptYG2TA9pj8yqVG/FZ7LTQjri2ht+ED9E0qXYaGbEojC3qVxSlEstBLnbRhp4ZPcWNzYw7vw/1D+UWmX3o+XZmlCED11APFMgTHc8yVHpq594qju22BUEff+v525VD53PssAv/Wjx1OztSXSGwOY1ydAYBN4+An+pGgHjVTWLUHkRYrRQNMsRwwTgNwHmaZiO+Qj28iIQpithhyUCPvLMn7PlLxJDAE1/ugPKAYSv+Z95De+NI7mP0WuaopETukZXhxua1yh77Wplq7Va9CfNYkE/Th9lx7eiAZar1g+XpFfeQmFXjMTHKujsE1BwFW98mcIzIWEr7eVhMjozCmXAXZe9HK03LSn456VQ+OJmvxfEJEAO/bQWrw5yYb65xqa8dz/5huaFAA6s/9rKC7m580lQ4CXMy9gdIfx7Pisr737NsG1xFr8OFshCiHMDt4cOwRtrCIIg1z+6HBXoBlecmFY8Tc75VsJc2p0M3dEQd2CMlChRbDthpjKGNaiGz13TB90wslfEHbj88vSVeHmCWBu30BlvgiOdMc9+eyzRd65Dzk4XWHrexXhHEptkbo6CZXLBv1agTTjc/6olN1wzafdN38V2t8DwOUJAAQSr8c3CnLIW3If50V+AGTyoKRniYUBiM0+NWzzUHiBXNEU01ew6GQ3JPLqrdiCpZ/2W9TOn+5YHBchr3CRlMkBcoPXN6WR9P9KKfQusWhTba3YwCRXgjtwIHkVpJ4ab4slU2C4dc0UIfeTQ5FF1dAK6zeFTkdGiLO9Pfq9aXcRiNHhCM45LEq7jmkpnuhI='}}]

**Question:** How much protein does the Sambar contain?
**Response:** [{'type': 'text', 'text': 'The information is not available in the provided recipe documents.', 'extras': {'signature': 'EugKCuUKARFNMg8CDpN1QSggpmHTeIl4K8I8Ma+I5CNK2tR1YGGt77wDEaOnLg7N36v40qDCKDYfNLGWqRpbhO4bKw4Qpzp/38AoqPxz4xM6Qq5SX1buE/k0YeS5rJ2/sEVUzEKfxdMGnlCOHgFHHSnG9oHRKFAewB3cX4FCZioyIMKzKlF+rTbmXlx+oRMWtKpYoYtH3gIjjbH7U5TN6zRJpAgTXPCI3/Vrl3Y+M6rZ0e5ZCgt8vF282Bx1eSnoiPIVYRpghkZN/4331xYl8fhhVHi3MGapS68iWH6dizlayH4cmq1npTACC5ml7Ox7kC66ORg8kX/uthAqQ/oV2ehmN6ZahE5kUmhtzBqTNp6TliJohXv7qlhcum1pz2ELDjm1wnHkO32mRmZmDw/XwRJQp4nGIijhOqGKAVkhcMtnjvvqUwX+4pBvTdUq/FAWgDtI5caK9eWST1Zdd1KySy9vKhbpVtpk49+e47sPnKTleux77AqtL7wI+hwkeljTraph+dsPYYA3vo0cUDVeSISCuKlgYmSiEG5NdYMH15ByeNiEdj/qPwNsiQzR2GyDk4AGToTpuAz+wjxC3IQdIjABmjIRyIHHX6sdz2DmaSg00hHGuhONmanAs+g0CDrtFnVG06lZzmhTGDyipSHDIFIELL+/sUn4ZH8D/2FK2x3Wwf2Tz/0jEjspKVSBUeD+UplKCsSOzpObLJDudtc+KGehHf4uOOBASAb4jkqsybNzdPUsHMwWA3GzJK8VS8VKkzl466RP4EmddC+cLmiiYmG1NTMhG9Ex9uQ8Fe2Rt1BpJIsAj7WspmISJDdhT4rKORgWlgbFjPUYLejFosUDU0RHi3KxOKLRg36+fZcFKLUHm3CL5LeZsokrpUK/6WkWhzPPGvgFOaG02wm2SPdaEVzIxNpPL728HA6r04qcG8r0iWUbGF6fM9BZCd7ohTQQRc6t27GfaoLjAmmZjyONIW+27AKS35PpENrZ4QWx6RvMlo07r1IX6lGPhc6uu/kdzOlmCQpMeqL0HJkFedSN/Tja3i4QKD34nxHgkWcd6g2CB3BUQU3L3sGRg+X53xtq75wFNwksBCsXEDVmVYyeNk8Y4m6yig0hSU/7ioOmEuhokm1/IMOvk9jlBbIV1YMSAQMmsZD1dLchO1x8AV1+kRSCQ2ChD2vIVZu1xTvBc76STNKDcdxZ9vtG1S6meeSdXLs9lUugoZBmi2HdKIh8E9Z/Szmqp4lL8IoWewMb31tptggNaRojRMC8Djc0bTxingjw7rabT/Hr8qoC+9GI+0w34rZtVPLbHB8eJ7rp8XWKHQyXxFJfej28ZmTVrigBJifA16UZarCAXxbaj58Twc9TBleTCFaGIVFvKdeDlEny0YWcpmxUhWXhV6L1HwnCcjNo+Q4xQ2QaF8/X72NheN48tzNuOb9fdJ3kuOssj52qWM2e1d2NuUVHFDG9JpEbRno65z0duQ4JIec8I+v0D1UGES+ghj06klCLNqYl/eWxKQeBeTGPRNw6i1GLBKkcuCbgf5tOEex2+ageDelM/Ufh0rRHI+vBphdqx4mo9DSGoawyJsPnqcwnJsIDMx8z5Au0h9VGxcw4KqQzJzzvF/RQkfAG9C4rtYr0cF2q0DQMAa2J7iyV+lw/1hGO75le0PoET8yWRjBi+EXnd/ezDKHrZLF0UmH1KGG7ZfgGK6mYN/Mh1tf44Zi66t6OLBfcc+o0makHyTKVEfxkA2KSIw2eCNrJYKNGaOzdTEWK3kt2yqskCInPhDGwm3yaSCDj6NwqzuhLx1Qmte9ysBejnD6P5Z16SfFpSiRdm6RVBJeofXtCBdcizGcbpQ=='}}]

**Question:** What is the vitamin C content of the Rasam?
**Response:** [{'type': 'text', 'text': 'The information is not available in the provided recipe documents.', 'extras': {'signature': 'EpwJCpkJARFNMg/iGJDpjXqE45Y/HuciCTqDQVlTMKdy4wvFrNeCJe1DQA//sJ+Wqe+nVrj4/NrY7O+src+fZs/SQtzu+RMRI7Vs6ZpRFt68im0FFtUOjZXUPASZ/3eKubLrfEgxN8/Kj7LxXShv1sBfUW77OcrIMGm1QuoFJN0rDJDManPsa5vWt7+6qru1tvnavcp9zWxCy+H/EyV1LGWHLCg0GiC2+d0cgyh7mNMHBiWYWNZZt6pXwt2I8VHYL/nAsaKcQDMTzEDqIx7GpW3XasPEOuAdlJKKsdaI/BiamStkttZTPdNqjZjup48E6tC3zGVJa80nwAEhUSLg/XdCqx9Jne+nO2j1Hfn5jkbdlNB7Lo2iLlGOkcaVS5hYCdt5bpjGBdN19C03u+0n8xyH6fI5kibW8/TpEw521SF5eMr/E5Fzm6bvh4ZiRNrL4rnmR/Xllk3tinXaxNr1vEv+mL4Vn1tudoqJUHXbAjsTZyvx61Ud35iGjaEjmILxuCLB29d4BeM6MBW5/yqp5sZXlXA2fHIkcFbvr/ZzhLi+ok6p6BrXyYjks2r0zFisM5S3u4YLJl6p70O0o8CCwYGgtyI+YLlUmahxzNLQhgyxTKn3TTsR9YeeBw0SBboFlV9bptHf9duLcCYL/Qk4J97qE3qDOzabJGUB3gkO7MmsPYAHYgkQJB31f0t7UPFjnI/TmQSoDQqLP5jxO7vyNAUaBj1i0MUUeuIS1NyGdVvKE89NFuEvMKNRdh9xVBPYljzgrzKwttUpgU0E818zzMBFzqvbnO17w2h+Ds8xWYYs2ivPJs5/CH6kT32yrYJrvwZynTrKXDve6njRx0wUCbv9BlWwwDGKW30jA5m/XyBoqNtzqbub3+rwvjCOw/4pGpoZ2EeAFUApvxOL0AP6xcnmvx8AtmWBTaTfq00YoKyR3sNW7kAW2/16NP1PiKl0nTPXxvJZLL184Mq7R5hsAqYpHusd7EEzcnNOiWvf0/mfSZHu/Wp7J1gT7RmXRL3pmPYn21T1LIxqrTYZGmyQl2m4F8+/l6AXfHQmeQAS4ngE5dF1w4ruarlvHeufcuDNPUpKgwiGLrMrkTxfpbxfZawjFwWq7UZ0OSxv2/2aB+XbKTOoQvHRdDfYCiD3H0WRjV2/p+doaQi5YZk/It5/OJ3CNfPsfPqKgZgsl+zcJWdomix5EVfCpgLp2HzNXXV/ZB7Gvw0a0KEuQxfj304JtAzw2KtP6ZsrsRsBm2qhLZ3ZFgV6YMXqT0zdw3hAm+x4ACpbn5sn/nBEMZx/2qUY9ypoO5SkC0cRgQsVVe2jfNWLfoakQYUI0pzosuczoqZV+CLzXzk4wLG5IYd7huDzn5tkc09ZzBfNgExH4S7Wk04tzOt0uJMyrAzeNjHad/AeRFNDsM+9F1pNZxFRNNQTFxuHAOY68Pq1cSfKXHAsMCfAjCZAmGtG1BOLqPwtuuWJIHY1EdnDzadILF0ul8/8xc9pmy3fh2ZFUvXhKFErnijWkcEXOhBDC35GfWa6rQZuUI7XbXMQurwGtqW+dx2cVbE5shKMHyb2btEqVF246A=='}}]

## 6. Chunker Decision

The **Structure-Aware Chunker** should be kept. By logically grouping recipe components (e.g. attaching the Recipe Title and Table Headers to every ingredient row), it prevents critical information from being orphaned. The baseline chunker often splits ingredient amounts from the context of what ingredient they belong to, or separates an ingredient list from the actual recipe name, leading to missing context during vector retrieval.

## 7. Retrieval Failure Analysis

*(Automatically documented based on results)*

**Failed Question:** How much salt is used in the Idli recipe?
Top retrieved chunk did not contain the exact expected answer, or semantic similarity prioritized method steps over ingredients.