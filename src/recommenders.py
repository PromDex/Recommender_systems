import pandas as pd
import numpy as np

# Для работы с матрицами
from scipy.sparse import csr_matrix

# Матричная факторизация
from implicit.als import AlternatingLeastSquares
from implicit.nearest_neighbours import ItemItemRecommender  # нужен для одного трюка
from implicit.nearest_neighbours import bm25_weight, tfidf_weight, BM25Recommender, CosineRecommender, TFIDFRecommender


class MainRecommender:
    """Рекоммендации, которые можно получить из ALS
    Input
    -----
    user_item_matrix: pd.DataFrame
        Матрица взаимодействий user-item
    """

    def __init__(self, data: pd.DataFrame, weighting: bool = True):

        

        # Топ покупок каждого юзера
        self.top_purchases = data.groupby(['user_id', 'item_id'])['quantity'].count().reset_index()
        self.top_purchases.sort_values('quantity', ascending=False, inplace=True)
        self.top_purchases = self.top_purchases[self.top_purchases['item_id'] != 999999]

        # Топ покупок по всему датасету
        self.overall_top_purchases = data.groupby('item_id')['quantity'].count().reset_index()
        self.overall_top_purchases.sort_values('quantity', ascending=False, inplace=True)
        self.overall_top_purchases = self.overall_top_purchases[self.overall_top_purchases['item_id'] != 999999]
        self.overall_top_purchases = self.overall_top_purchases.item_id.tolist()

        self.user_item_matrix = self._prepare_matrix(data)  # pd.DataFrame
        self.id_to_itemid, self.id_to_userid, \
        self.itemid_to_id, self.userid_to_id = self._prepare_dicts(self.user_item_matrix)

        if weighting:
            self.user_item_matrix = bm25_weight(self.user_item_matrix.T, B=0.1, K1=5)

        self.model = self.fit(self.user_item_matrix)
        self.model_bm25 = self.fit_bm25(self.user_item_matrix)
        self.model_tfidf = self.fit_tfidf(self.user_item_matrix)
        self.model_cosine = self.fit_cosine(self.user_item_matrix)
        self.own_recommender = self.fit_own_recommender(self.user_item_matrix)

    @staticmethod
    def _prepare_matrix(data: pd.DataFrame):
        """Готовит user-item матрицу"""
        user_item_matrix = pd.pivot_table(data,
                                          index='user_id',
                                          columns='item_id',
                                          values='quantity',  # Можно пробовать другие варианты
                                          aggfunc='count',
                                          fill_value=0
                                          )

        user_item_matrix = user_item_matrix.astype(float)  # необходимый тип матрицы для implicit     

        return user_item_matrix

    @staticmethod
    def _prepare_dicts(user_item_matrix):
        """Подготавливает вспомогательные словари"""

        userids = user_item_matrix.index.values
        itemids = user_item_matrix.columns.values

        matrix_userids = np.arange(len(userids))
        matrix_itemids = np.arange(len(itemids))

        id_to_itemid = dict(zip(matrix_itemids, itemids))
        id_to_userid = dict(zip(matrix_userids, userids))

        itemid_to_id = dict(zip(itemids, matrix_itemids))
        userid_to_id = dict(zip(userids, matrix_userids))

        return id_to_itemid, id_to_userid, itemid_to_id, userid_to_id

    @staticmethod
    def fit_own_recommender(user_item_matrix):
        """Обучает модель, которая рекомендует товары, среди товаров, купленных юзером"""

        own_recommender = ItemItemRecommender(K=1, num_threads=4)
        own_recommender.fit(csr_matrix(user_item_matrix).T.tocsr())

        return own_recommender

    @staticmethod
    def fit(user_item_matrix, n_factors=512, regularization=0.04, iterations=20, num_threads=0):
        """Обучает ALS"""

        model = AlternatingLeastSquares(factors=n_factors,
                                        regularization=regularization,
                                        iterations=iterations,
                                        num_threads=num_threads)
        model.fit(csr_matrix(user_item_matrix).T.tocsr())

        return model
    
    @staticmethod
    def fit_bm25(user_item_matrix):
        """Обучает BM25"""

        model = BM25Recommender()
        model.fit(csr_matrix(user_item_matrix).T.tocsr())

        return model
    
    @staticmethod
    def fit_tfidf(user_item_matrix):
        """Обучает TFIDF"""

        model = TFIDFRecommender()
        model.fit(csr_matrix(user_item_matrix).T.tocsr())

        return model
    
    @staticmethod
    def fit_cosine(user_item_matrix):
        """Обучает CosineRecommender"""

        model = CosineRecommender(K=2)
        model.fit(csr_matrix(user_item_matrix).T.tocsr())

        return model

    def _update_dict(self, user_id):
        """Если появился новыю user / item, то нужно обновить словари"""

        if user_id not in self.userid_to_id.keys():
            max_id = max(list(self.userid_to_id.values()))
            max_id += 1

            self.userid_to_id.update({user_id: max_id})
            self.id_to_userid.update({max_id: user_id})

            
    def _get_similar_item(self, item_id):
        """Находит похожий товар для заданного item_id"""
    
        recs = self.model.similar_items(self.itemid_to_id[item_id], N=2)
    
        for rec in recs:
            if rec[0] != item_id:
                return self.id_to_itemid[rec[0]]
    
        return None

    
    def _extend_with_top_popular(self, recommendations, N=5):
        """Если кол-во рекоммендаций < N, то дополняем их топ-популярными"""

        if len(recommendations) < N:
            recommendations.extend(self.overall_top_purchases[:N])
            recommendations = recommendations[:N]

        return recommendations

    def _get_recommendations(self, user, model, N=5):
        """Рекомендации через стардартные библиотеки implicit"""

        self._update_dict(user_id=user)
        res = [self.id_to_itemid[rec] for rec in model.recommend(userid=self.userid_to_id[user],
                                        user_items=csr_matrix(self.user_item_matrix).tocsr(),
                                        N=N,
                                        filter_already_liked_items=False,
                                        filter_items=[self.itemid_to_id[999999]],
                                        recalculate_user=False)[0]]

        res = self._extend_with_top_popular(res, N=N)

        assert len(res) == N, 'Количество рекомендаций != {}'.format(N)
        return res

    def get_als_recommendations(self, user, N=5):
        """Рекомендации через стардартные библиотеки implicit"""

        self._update_dict(user_id=user)
        return self._get_recommendations(user, model=self.model, N=N)
    
    
    def get_bm25_recommendations(self, user, N=5):
        """Рекомендации через стардартные библиотеки implicit"""

        self._update_dict(user_id=user)
        return self._get_recommendations(user, model=self.model_bm25, N=N)
    
    def get_tfidf_recommendations(self, user, N=5):
        """Рекомендации через стардартные библиотеки implicit"""

        self._update_dict(user_id=user)
        return self._get_recommendations(user, model=self.model_tfidf, N=N)
    
    def get_cosine_recommendations(self, user, N=5):
        """Рекомендации через стардартные библиотеки implicit"""

        self._update_dict(user_id=user)
        return self._get_recommendations(user, model=self.model_cosine, N=N)

    def get_own_recommendations(self, user, N=5):
        """Рекомендуем товары среди тех, которые юзер уже купил"""

        self._update_dict(user_id=user)
        return self._get_recommendations(user, model=self.own_recommender, N=N)

    
    def get_similar_items_recommendation(self, user_id, N=5):
        """Рекомендуем товары, похожие на топ-N купленных юзером товаров"""
        
        top_users_purchases = self.top_purchases[self.top_purchases['user_id'] == user_id].head(N)

        res = top_users_purchases['item_id'].apply(lambda x: self._get_similar_item(x)).tolist()
        res = self._extend_with_top_popular(res, N=N)

        assert len(res) == N, 'Количество рекомендаций != {}'.format(N)
        return res
    
    
    
    def get_similar_users_recommendation(self, user_id, N=5):
        """Рекомендуем топ-N товаров, среди купленных похожими юзерами"""

        res = []

        # Находим топ-N похожих пользователей
        similar_users = self.model.similar_users(self.userid_to_id[user_id], N=N + 1)
        similar_users = [self.id_to_userid.get(str(rec[0])) for rec in similar_users if str(rec[0]) in self.id_to_userid]
        similar_users = similar_users[1:]  # удалим юзера из запроса

        for _user_id in similar_users:
            res.extend(self.get_own_recommendations(_user_id, N=1))

        res = self._extend_with_top_popular(res, N=N)

        assert len(res) == N, 'Количество рекомендаций != {}'.format(N)
        return res
    
    
    def _get_scores(self, user, model, N=5):
        self._update_dict(user_id=user)

        scores_rec = [rec for rec in model.recommend(
            userid=self.userid_to_id[user],
            user_items=csr_matrix(self.user_item_matrix).tocsr(),
            N=N,
            filter_already_liked_items=False,
            filter_items=[self.itemid_to_id[999999]],
            recalculate_user=True
        )[1]]

        if len(scores_rec) < N:
            additional_rec = [item_score for item_score in model.rank_items(
                userid=self.userid_to_id[user],
                user_items=csr_matrix(self.user_item_matrix).tocsr(),
                selected_items=[self.itemid_to_id[item] for item in self.overall_top_purchases],
                recalculate_user=True
            )[1]]
            scores_rec.extend(additional_rec)

        scores_rec = scores_rec[:N]  # Take the available recommendations up to N

        assert len(scores_rec) == N, 'Количество рекомендаций != {}'.format(N)

        return scores_rec   
    
    def get_als_scores(self, user, N=5):
        """Скоры товаров рекомендованных через стардартные библиотеки implicit"""

        self._update_dict(user_id=user)
        return self._get_scores(user, model=self.model_als, N=N)
    
    
    def get_bm25_scores(self, user, N=5):
        """Скоры товаров рекомендованных через стардартные библиотеки implicit"""

        self._update_dict(user_id=user)
        return self._get_scores(user, model=self.model_bm25, N=N)
    
    def get_tfidf_scores(self, user, N=5):
        """Скоры товаров рекомендованных через стардартные библиотеки implicit"""

        self._update_dict(user_id=user)
        return self._get_scores(user, model=self.model_tfidf, N=N)
    
    def get_cosine_scores(self, user, N=5):
        """Скоры товаров рекомендованных через стардартные библиотеки implicit"""

        self._update_dict(user_id=user)
        return self._get_scores(user, model=self.model_cosine, N=N)

    def get_own_scores(self, user, N=5):
        """Скоры товаров рекомендованных среди тех, которые юзер уже купил"""

        self._update_dict(user_id=user)
        return self._get_scores(user, model=self.own_recommender, N=N)
    
    def tfidf_score(self, user, item, model):
        """Скор товара на основе TFIDF"""

        scores_rec = model.rank_items(userid=self.userid_to_id[user],
                                                         user_items=csr_matrix(self.user_item_matrix).tocsr(),
                                                         selected_items=[self.itemid_to_id[item] for item in item],
                                                         recalculate_user=True)[0][1]

        return scores_rec

