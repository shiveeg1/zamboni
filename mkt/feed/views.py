from django.utils.datastructures import MultiValueDictKeyError

from rest_framework import response, serializers, status, viewsets
from rest_framework.exceptions import ParseError
from rest_framework.filters import OrderingFilter
from rest_framework.parsers import JSONParser
from rest_framework.response import Response
from rest_framework.views import APIView

import mkt
from mkt.api.authentication import (RestAnonymousAuthentication,
                                    RestOAuthAuthentication,
                                    RestSharedSecretAuthentication)
from mkt.api.authorization import AllowReadOnly, AnyOf, GroupPermission
from mkt.api.base import (CORSMixin, cors_api_view, MarketplaceView,
                          SlugOrIdMixin)
from mkt.collections.views import CollectionImageViewSet
from mkt.webapps.models import Webapp

from .authorization import FeedAuthorization
from .models import FeedApp, FeedBrand, FeedCollection, FeedItem
from .serializers import (FeedAppSerializer, FeedBrandSerializer,
                          FeedCollectionSerializer, FeedItemSerializer)


class BaseFeedCollectionViewSet(CORSMixin, SlugOrIdMixin, MarketplaceView,
                                viewsets.ModelViewSet):
    """
    Base viewset for subclasses of BaseFeedCollection.
    """
    serializer_class = None
    queryset = None
    cors_allowed_methods = ('get', 'post', 'delete', 'patch', 'put')
    permission_classes = [FeedAuthorization]
    authentication_classes = [RestOAuthAuthentication,
                              RestSharedSecretAuthentication,
                              RestAnonymousAuthentication]

    exceptions = {
        'doesnt_exist': 'One or more of the specified `apps` do not exist.'
    }

    def list(self, request, *args, **kwargs):
        page = self.paginate_queryset(
            self.filter_queryset(self.get_queryset()))
        serializer = self.get_pagination_serializer(page)
        return response.Response(serializer.data)

    def set_apps(self, obj, apps):
        if apps:
            try:
                obj.set_apps(apps)
            except Webapp.DoesNotExist:
                raise ParseError(detail=self.exceptions['doesnt_exist'])

    def create(self, request, *args, **kwargs):
        apps = request.DATA.pop('apps', [])
        serializer = self.get_serializer(data=request.DATA,
                                         files=request.FILES)
        if serializer.is_valid():
            self.pre_save(serializer.object)
            self.object = serializer.save(force_insert=True)
            self.set_apps(self.object, apps)
            self.post_save(self.object, created=True)
            headers = self.get_success_headers(serializer.data)
            return response.Response(serializer.data,
                                     status=status.HTTP_201_CREATED,
                                     headers=headers)
        return response.Response(serializer.errors,
                                 status=status.HTTP_400_BAD_REQUEST)

    def update(self, request, *args, **kwargs):
        apps = request.DATA.pop('apps', [])
        self.set_apps(self.get_object(), apps)
        ret = super(BaseFeedCollectionViewSet, self).update(
            request, *args, **kwargs)
        return ret


class FeedItemViewSet(CORSMixin, viewsets.ModelViewSet):
    """
    A viewset for the FeedItem class, which wraps all items that live on the
    feed.
    """
    authentication_classes = [RestOAuthAuthentication,
                              RestSharedSecretAuthentication,
                              RestAnonymousAuthentication]
    permission_classes = [AnyOf(AllowReadOnly,
                                GroupPermission('Feed', 'Curate'))]
    filter_backends = (OrderingFilter,)
    queryset = FeedItem.objects.all()
    cors_allowed_methods = ('get', 'delete', 'post', 'put', 'patch')
    serializer_class = FeedItemSerializer


class FeedBuilderView(CORSMixin, APIView):
    authentication_classes = [RestOAuthAuthentication,
                              RestSharedSecretAuthentication]
    permission_classes = [GroupPermission('Feed', 'Curate')]
    cors_allowed_methods = ('put',)

    def put(self, request, *args, **kwargs):
        """
        For each region in the object:
        Deletes all of the (carrier-less) FeedItems in the region.
        Batch create all of the FeedItems in order for each region.

        -- feed - object of regions that point to a list of feed
                  element IDs (as well as their type) .
        {
            'us': [
                ['app', 36L],
                ['app', 42L],
                ['collection', 12L],
                ['brand', 12L]
            ]
        }
        """
        regions = [mkt.regions.REGIONS_DICT[region].id
                   for region in request.DATA.keys()]
        FeedItem.objects.filter(
            carrier=None, region__in=regions).delete()

        feed_items = []
        for region, feed_elements in request.DATA.items():
            for order, feed_element in enumerate(feed_elements):
                try:
                    item_type, item_id = feed_element
                except ValueError:
                    return response.Response(
                        'Expected two-element arrays.',
                        status=status.HTTP_400_BAD_REQUEST)
                feed_item = {
                    'region': mkt.regions.REGIONS_DICT[region].id,
                    'order': order,
                    'item_type': item_type,
                }
                feed_item[item_type + '_id'] = item_id
                feed_items.append(FeedItem(**feed_item))

        FeedItem.objects.bulk_create(feed_items)
        return Response(status=status.HTTP_201_CREATED)


class FeedAppViewSet(CORSMixin, MarketplaceView, SlugOrIdMixin,
                     viewsets.ModelViewSet):
    """
    A viewset for the FeedApp class, which highlights a single app and some
    additional metadata (e.g. a review or a screenshot).
    """
    authentication_classes = [RestOAuthAuthentication,
                              RestSharedSecretAuthentication,
                              RestAnonymousAuthentication]
    permission_classes = [AnyOf(AllowReadOnly,
                                GroupPermission('Feed', 'Curate'))]
    filter_backends = (OrderingFilter,)
    queryset = FeedApp.objects.all()
    cors_allowed_methods = ('get', 'delete', 'post', 'put', 'patch')
    serializer_class = FeedAppSerializer

    def list(self, request, *args, **kwargs):
        page = self.paginate_queryset(
            self.filter_queryset(self.get_queryset()))
        serializer = self.get_pagination_serializer(page)
        return response.Response(serializer.data)


class FeedAppImageViewSet(CollectionImageViewSet):
    queryset = FeedApp.objects.all()


class FeedBrandViewSet(BaseFeedCollectionViewSet):
    """
    A viewset for the FeedBrand class, a type of collection that allows editors
    to quickly create content without involving localizers.
    """
    serializer_class = FeedBrandSerializer
    queryset = FeedBrand.objects.all()


class FeedCollectionViewSet(BaseFeedCollectionViewSet):
    """
    A viewset for the FeedCollection class.
    """
    serializer_class = FeedCollectionSerializer
    queryset = FeedCollection.objects.all()
